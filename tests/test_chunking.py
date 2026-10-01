from xia.chunking import trocear

LARGO = "Texto de relleno para superar el mínimo de sección. " * 6


def test_conserva_ruta_de_encabezados():
    md = f"# Guía\n\n## Estados\n\n### Pendiente\n\n{LARGO}\n"
    fr = trocear(md, "Guía")
    assert len(fr) == 1
    assert fr[0].encabezados == "Guía > Estados > Pendiente"


def test_no_duplica_el_titulo_si_es_el_h1():
    fr = trocear(f"# Guía\n\n{LARGO}", "Guía")
    assert fr[0].encabezados == "Guía"


def test_hash_dentro_de_codigo_no_es_encabezado():
    md = f"# Guía\n\n```bash\n# esto es un comentario\necho hola\n```\n\n{LARGO}"
    fr = trocear(md, "Guía")
    assert all("comentario" not in f.encabezados for f in fr)
    assert any("# esto es un comentario" in f.texto for f in fr)


def test_secciones_cortas_se_pegan_a_la_siguiente():
    md = f"# Guía\n\n## Corta\n\nUna línea.\n\n## Larga\n\n{LARGO}"
    fr = trocear(md, "Guía")
    assert len(fr) == 1
    assert "Una línea." in fr[0].texto
    assert fr[0].encabezados == "Guía > Larga"


def test_respeta_el_maximo_de_caracteres():
    parrafos = "\n\n".join(f"Párrafo {i}. " + "palabra " * 40 for i in range(30))
    fr = trocear(f"# Guía\n\n{parrafos}", "Guía", max_chars=800)
    assert len(fr) > 1
    assert all(len(f.texto) <= 800 for f in fr)


def test_bloque_de_codigo_no_se_parte_si_cabe():
    codigo = "```sql\n" + "\n\n".join(f"SELECT {i};" for i in range(5)) + "\n```"
    fr = trocear(f"# Guía\n\n{LARGO}\n\n{codigo}", "Guía", max_chars=1500)
    assert any(codigo in f.texto for f in fr)


def test_ordenes_consecutivos():
    parrafos = "\n\n".join("palabra " * 80 for _ in range(10))
    fr = trocear(f"# Guía\n\n{parrafos}", "Guía", max_chars=700)
    assert [f.orden for f in fr] == list(range(len(fr)))
