"""Agente con herramientas: lo que decide la seguridad del diseño (validación, datos no confiables, cuota)."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from xia import acceso, agente, servicio
from xia.api import AgenteIn
from xia.errores import XiaError

HERRAMIENTAS = [
    {"nombre": "search_orders", "descripcion": "Busca órdenes", "parametros": {
        "type": "object",
        "properties": {"status": {"type": "string", "enum": ["Draft", "Sent"]}, "limit": {"type": "integer"},
                       "pending_for_me": {"type": "boolean"}}}},
    {"nombre": "get_order", "descripcion": "Detalle", "parametros": {
        "type": "object", "properties": {"order_code": {"type": "string"}}, "required": ["order_code"]}},
]
IDENTIDAD = acceso.Identidad(usuario="ana@stockline.test", permisos=frozenset({"orders.view"}))


def llamada(nombre, **args):
    return {"function": {"name": nombre, "arguments": args}}


@pytest.fixture(autouse=True)
def sin_pipeline_real(monkeypatch):
    """Ningún test de este módulo debe tocar Ollama ni la base de datos por accidente."""
    def prohibido(*a, **k):
        raise AssertionError("el pipeline real no debe ejecutarse en un test unitario")

    monkeypatch.setattr(agente.pipeline, "ejecutar", prohibido)


@pytest.fixture
def modelo(monkeypatch):
    """Sustituye al modelo: `respuestas` es la cola de mensajes que devolverá; `vistos` guarda lo que recibió."""
    estado = SimpleNamespace(respuestas=[], vistos=[])

    def falso(mensajes, herramientas, modelo=None, temperatura=0.1):
        estado.vistos.append((mensajes, herramientas))
        return estado.respuestas.pop(0)

    monkeypatch.setattr(agente, "conversar", falso)
    monkeypatch.setattr(agente.acceso, "alcance", lambda _i: SimpleNamespace(areas=frozenset({"stockline"}), documentos=None))
    return estado


def correr(mensajes=None, instrucciones=None, idioma="es"):
    mensajes = mensajes or [{"rol": "user", "texto": "hola"}]
    return agente.ejecutar(IDENTIDAD, mensajes, HERRAMIENTAS, instrucciones, idioma)


class TestPideCredenciales:
    @pytest.mark.parametrize("texto", [
        "Por favor, escribe tu contraseña en el chat para continuar.",
        "Para seguir, ingresa tu clave de acceso.",
        "Envíame tu contraseña y lo reviso.",
        "Please enter your password to continue.",
        "Send me the verification code you received.",
        "Comparte tu token de sesión",
    ])
    def test_detecta_el_pedido(self, texto):
        assert agente.pide_credenciales(texto)

    @pytest.mark.parametrize("texto", [
        "La orden PO-2026-017 está en borrador.",
        "Tienes 7 órdenes esperando por ti.",
        "El administrador puede restablecer una contraseña desde Usuarios.",
        "The order was sent to the ERP.",
    ])
    def test_no_se_dispara_con_texto_normal(self, texto):
        assert not agente.pide_credenciales(texto)


class TestArgumentos:
    PARAMS = HERRAMIENTAS[0]["parametros"]

    def test_acepta_lo_declarado(self):
        assert agente.argumentos_validos(self.PARAMS, {"status": "Draft", "limit": 5, "pending_for_me": True})

    @pytest.mark.parametrize("args", [
        {"status": "Borrador"}, {"limit": "5"}, {"limit": True}, {"pending_for_me": "yes"}, {"inventado": 1},
    ])
    def test_rechaza_lo_que_no_cumple_el_esquema(self, args):
        assert not agente.argumentos_validos(self.PARAMS, args)

    def test_exige_los_requeridos(self):
        assert not agente.argumentos_validos(HERRAMIENTAS[1]["parametros"], {})


class TestFiltroDeLlamadas:
    def test_descarta_herramientas_inventadas_y_argumentos_invalidos(self):
        validas = agente._filtrar_llamadas(
            [llamada("search_orders", status="Draft"), llamada("cancel_order", code="PO-1"),
             llamada("search_orders", status="Nope"), llamada("get_order")], HERRAMIENTAS)

        assert [(c.nombre, c.argumentos) for c in validas] == [("search_orders", {"status": "Draft"})]

    def test_cada_llamada_recibe_un_id_distinto(self):
        validas = agente._filtrar_llamadas([llamada("get_order", order_code="A"), llamada("get_order", order_code="B")],
                                           HERRAMIENTAS)
        assert len({c.id for c in validas}) == 2


class TestMensajesAlModelo:
    def test_todo_resultado_viaja_marcado_como_dato_no_confiable(self):
        salida = agente.mensajes_a_ollama([
            {"rol": "user", "texto": "pendientes"},
            {"rol": "assistant", "texto": "", "llamadas": [{"nombre": "orders_summary", "argumentos": {}}]},
            {"rol": "tool", "herramienta": "orders_summary", "texto": '{"awaitingMe":7}'},
        ], "SISTEMA")

        assert salida[0] == {"role": "system", "content": "SISTEMA"}
        assert salida[2]["tool_calls"][0]["function"]["name"] == "orders_summary"
        assert salida[3]["role"] == "tool" and salida[3]["tool_name"] == "orders_summary"
        assert "DATOS NO CONFIABLES" in salida[3]["content"] and '{"awaitingMe":7}' in salida[3]["content"]

    def test_recorta_los_resultados_largos_y_la_conversacion(self, monkeypatch):
        monkeypatch.setattr(agente.get_settings(), "agente_max_chars_herramienta", 50)
        monkeypatch.setattr(agente.get_settings(), "agente_max_mensajes", 3)
        mensajes = [{"rol": "user", "texto": f"p{i}"} for i in range(6)]
        mensajes.append({"rol": "tool", "herramienta": "t", "texto": "x" * 500})

        salida = agente.mensajes_a_ollama(mensajes, "S")

        assert len(salida) == 1 + 3
        assert "x" * 51 not in salida[-1]["content"]


class TestEjecutar:
    def test_el_modelo_nunca_responde_de_memoria_en_el_primer_paso(self, modelo, monkeypatch):
        """Sin herramientas, lo que diga el modelo se descarta: manda el pipeline fundamentado en la documentación."""
        modelo.respuestas.append({"content": "Normalmente lo hace el comprador."})
        preguntas = []

        def pipeline_falso(pregunta, areas, modelo_, historial=None, alcance=None, idioma="es"):
            preguntas.append(pregunta)
            return SimpleNamespace(respuesta="Según el manual, quien tiene el permiso de importación.", fuentes=[],
                                   sin_contexto=False, modelo="m", fragmentos_ids=[], areas_consultadas=["stockline"])

        monkeypatch.setattr(agente.pipeline, "ejecutar", pipeline_falso)

        r = correr([{"rol": "user", "texto": "¿Quién puede importar una orden?"}])

        assert preguntas == ["¿Quién puede importar una orden?"]
        assert r.texto == "Según el manual, quien tiene el permiso de importación." and "comprador" not in r.texto

    def test_tras_resultados_de_herramientas_el_modelo_si_redacta_con_los_datos(self, modelo, monkeypatch):
        modelo.respuestas.append({"content": "Tienes 7 órdenes esperando."})
        monkeypatch.setattr(agente.pipeline, "ejecutar", lambda *a, **k: pytest.fail("no debe consultar documentación"))

        r = correr([{"rol": "user", "texto": "pendientes"},
                    {"rol": "assistant", "texto": "", "llamadas": [{"nombre": "orders_summary", "argumentos": {}}]},
                    {"rol": "tool", "herramienta": "orders_summary", "texto": '{"awaitingMyAction":7}'}])

        assert r.texto == "Tienes 7 órdenes esperando." and not r.llamadas

    def test_devuelve_las_llamadas_para_que_las_ejecute_la_aplicacion(self, modelo):
        modelo.respuestas.append({"content": "", "tool_calls": [llamada("search_orders", status="Draft")]})

        r = correr([{"rol": "user", "texto": "borradores"}])

        assert r.texto is None
        assert [(c.nombre, c.argumentos) for c in r.llamadas] == [("search_orders", {"status": "Draft"})]

    def test_la_documentacion_se_resuelve_en_xia_y_cierra_el_turno(self, modelo, monkeypatch):
        modelo.respuestas.append({"content": "", "tool_calls": [
            llamada("search_documentation", question="¿Cómo reintento un envío?"), llamada("get_order", order_code="X")]})
        vistos = {}

        def pipeline_falso(pregunta, areas, modelo_, historial=None, alcance=None, idioma="es"):
            vistos.update(pregunta=pregunta, idioma=idioma, alcance=alcance)
            return SimpleNamespace(respuesta="Pulsa Reintentar.", fuentes=[{"area": "stockline", "documento": "d.md", "titulo": "ERP"}],
                                   sin_contexto=False, modelo="m", fragmentos_ids=[1], areas_consultadas=["stockline"])

        monkeypatch.setattr(agente.pipeline, "ejecutar", pipeline_falso)

        r = correr([{"rol": "user", "texto": "reintentar"}], idioma="en")

        assert r.texto == "Pulsa Reintentar." and not r.llamadas and r.fuentes[0]["titulo"] == "ERP"
        assert vistos["pregunta"] == "¿Cómo reintento un envío?" and vistos["idioma"] == "en"

    def test_la_herramienta_de_documentacion_solo_se_ofrece_si_hay_documentos_permitidos(self, modelo, monkeypatch):
        monkeypatch.setattr(agente.acceso, "alcance", lambda _i: SimpleNamespace(areas=frozenset(), documentos=[]))
        monkeypatch.setattr(agente.pipeline, "ejecutar", lambda *a, **k: SimpleNamespace(
            respuesta="r", fuentes=[], sin_contexto=True, modelo="m", fragmentos_ids=[], areas_consultadas=[]))
        modelo.respuestas.append({"content": "ok"})

        correr()

        nombres = [h["function"]["name"] for h in modelo.vistos[0][1]]
        assert nombres == ["search_orders", "get_order"]

    def test_bloquea_una_respuesta_que_pide_la_contrasena(self, modelo):
        modelo.respuestas.append({"content": "Por favor, escribe tu contraseña en el chat para continuar."})

        r = correr([{"rol": "user", "texto": "d"}, {"rol": "assistant", "texto": "", "llamadas": [{"nombre": "get_order", "argumentos": {"order_code": "X"}}]},
                    {"rol": "tool", "herramienta": "get_order", "texto": "{}"}])

        assert r.bloqueada and "contraseñas" in r.texto and "escribe tu" not in r.texto

    def test_las_instrucciones_de_la_aplicacion_se_suman_a_las_de_xia(self, modelo, monkeypatch):
        modelo.respuestas.append({"content": "ok"})
        monkeypatch.setattr(agente.pipeline, "ejecutar", lambda *a, **k: SimpleNamespace(
            respuesta="r", fuentes=[], sin_contexto=False, modelo="m", fragmentos_ids=[], areas_consultadas=[]))

        correr(instrucciones="Habla de Stockline.", idioma="en")

        sistema = modelo.vistos[0][0][0]["content"]
        assert "Habla de Stockline." in sistema and "English" in sistema and "DATOS" in sistema

    def test_una_llamada_inventada_no_rompe_el_turno_y_se_responde_con_la_documentacion(self, modelo, monkeypatch):
        modelo.respuestas.append({"content": "", "tool_calls": [llamada("borrar_todo")]})
        monkeypatch.setattr(agente.pipeline, "ejecutar", lambda *a, **k: SimpleNamespace(
            respuesta="No encontré eso en el manual.", fuentes=[], sin_contexto=True, modelo="m", fragmentos_ids=[],
            areas_consultadas=[]))

        r = correr()

        assert not r.llamadas and r.sin_contexto and r.texto == "No encontré eso en el manual."


class TestEntrada:
    def mensajes(self, *roles):
        return [{"rol": rol, "texto": "x"} for rol in roles]

    def test_no_puede_terminar_en_un_mensaje_del_asistente(self):
        with pytest.raises(ValidationError):
            AgenteIn(mensajes=self.mensajes("user", "assistant"))

    def test_termina_en_persona_o_en_resultado(self):
        AgenteIn(mensajes=self.mensajes("user"))
        AgenteIn(mensajes=self.mensajes("user", "assistant", "tool"))

    def test_el_nombre_de_la_herramienta_de_documentacion_esta_reservado(self):
        with pytest.raises(ValidationError):
            AgenteIn(mensajes=self.mensajes("user"), herramientas=[{"nombre": "search_documentation"}])

    @pytest.mark.parametrize("nombre", ["con espacio", "1empieza", "a" * 70, "x;drop"])
    def test_nombres_de_herramienta_invalidos(self, nombre):
        with pytest.raises(ValidationError):
            AgenteIn(mensajes=self.mensajes("user"), herramientas=[{"nombre": nombre}])


class TestCuota:
    @pytest.fixture
    def servicio_falso(self, monkeypatch):
        auditoria = []
        monkeypatch.setattr(servicio.cuota, "consultar", lambda _u: {"restantes": 0, "limite": 30})
        monkeypatch.setattr(servicio, "_auditar", lambda *a, **k: auditoria.append(k))
        monkeypatch.setattr(servicio.agente, "ejecutar", lambda *a, **k: agente.ResultadoAgente(texto="listo", modelo="m"))
        return auditoria

    def test_una_pregunta_nueva_sin_cuota_se_rechaza(self, servicio_falso):
        with pytest.raises(XiaError) as e:
            servicio.responder_agente(IDENTIDAD, [{"rol": "user", "texto": "hola"}], [], None)
        assert e.value.codigo == "cuota-agotada"
        assert servicio_falso[0]["intencion"] == "agente"

    def test_la_continuacion_tras_un_resultado_no_exige_cuota_y_no_la_gasta(self, servicio_falso):
        r = servicio.responder_agente(IDENTIDAD, [{"rol": "user", "texto": "p"},
                                                  {"rol": "tool", "herramienta": "t", "texto": "{}"}], [], None)
        assert r["tipo"] == "respuesta" and r["respuesta"] == "listo"
        assert servicio_falso[0]["intencion"] == "continuacion"
