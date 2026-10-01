from xia.redaccion import MARCA, redactar


def test_enmascara_valor_entre_comillas_y_conserva_la_clave():
    assert redactar('password: "Admin123!",') == f'password: "{MARCA}",'
    assert redactar("password = 'Admin123!'") == f"password = '{MARCA}'"
    assert redactar('-Body (@{userName="admin"; password="Admin123!"; x=1})') == \
        f'-Body (@{{userName="admin"; password="{MARCA}"; x=1}})'


def test_enmascara_variables_y_cadenas_de_conexion():
    assert redactar("Sap__Password=s3cr3t") == f"Sap__Password={MARCA}"
    assert redactar("Server=x;User Id=sa;Password=abc123;Encrypt=True") == f"Server=x;User Id=sa;Password={MARCA};Encrypt=True"
    assert redactar("JWT_SECRET=clave_super_secreta") == f"JWT_SECRET={MARCA}"


def test_enmascara_valor_en_markdown():
    assert redactar("- **Password:** `Admin123!`") == f"- **Password:** `{MARCA}`"
    assert redactar("| Password | `abc` |") == f"| Password | `{MARCA}` |"
    assert redactar("- **Username:** `admin`") == "- **Username:** `admin`"


def test_enmascara_jwt():
    assert MARCA in redactar("Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27")


def test_no_toca_texto_normal_ni_nombres_de_permiso():
    for t in ("El usuario es admin y la contraseña se envía en el campo password.",
              "permiso promocion.sobres.operate", "const token = localStorage.getItem('token')",
              "Con contraseña: Contraseña SAP", "idempotente por clave `Idempotency-Key` del cliente",
              "valida con `JWT_SECRET`, `JWT_ISSUER` y `JWT_AUDIENCE`"):
        assert redactar(t) == t
