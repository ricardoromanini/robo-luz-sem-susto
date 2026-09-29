"""Motor de páginas automatizadas em redes sociais (multi-página)."""

# Usa os certificados do sistema operacional (no Windows com antivírus que inspeciona HTTPS,
# como o Kaspersky, o Python sozinho recusa a conexão; o Windows já confia no antivírus).
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:  # na nuvem (Linux) não é necessário
    pass
