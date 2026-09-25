INSERT OR IGNORE INTO prefeituras (id, nome) VALUES ('prefeitura-quixada', 'Quixadá');

INSERT OR IGNORE INTO materiais (id, categoria, fator_emissaoipcc) VALUES
    ('papel', 'Papel', 1.0),
    ('plastico', 'Plástico', 1.0),
    ('vidro', 'Vidro', 1.0),
    ('metal', 'Metal', 1.0);

INSERT OR IGNORE INTO empresas (id, prefeitura_id, cnpj, razao_social, nome_fantasia, email, pwd_hash, empresa_status)
VALUES ('empresa-demo', 'prefeitura-quixada', '00000000000100', 'Empresa Demo LTDA', 'Empresa Demo',
        'empresa@demo.com', 'hashed_demo123', 'APROVADA');

INSERT OR IGNORE INTO usuarios_admin (id, id_prefeitura, nome, email, senha_hash, perfil)
VALUES ('gestor-demo', 'prefeitura-quixada', 'Gestor Demo', 'gestor@demo.com', 'hashed_demo123', 'GESTOR');
