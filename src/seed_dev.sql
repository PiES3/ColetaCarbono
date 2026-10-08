INSERT OR IGNORE INTO prefeituras (id, nome) VALUES ('prefeitura-quixada', 'Quixadá');
INSERT OR IGNORE INTO prefeituras (id, nome) VALUES ('prefeitura-quixeramobim', 'Quixeramobim');

INSERT OR IGNORE INTO materiais (id, categoria, fator_emissaoipcc) VALUES
    ('papel', 'Papel', 1.0),
    ('plastico', 'Plástico', 1.0),
    ('vidro', 'Vidro', 1.0),
    ('metal', 'Metal', 1.0);

INSERT OR IGNORE INTO empresas (id, prefeitura_id, cnpj, razao_social, nome_fantasia, email, pwd_hash, empresa_status, email_confirmado)
VALUES ('empresa-demo', 'prefeitura-quixada', '11222333000181', 'Empresa Demo LTDA', 'Empresa Demo',
        'empresa@demo.com', '$2b$12$EewUZscvfTEMpkYELJXRruH5oYa4ztKO8qr7K34pqpwlQgUbGLCwG', 'APROVADA', 1);

INSERT OR IGNORE INTO empresas (id, prefeitura_id, cnpj, razao_social, nome_fantasia, email, pwd_hash, empresa_status, email_confirmado)
VALUES ('empresa-quixeramobim', 'prefeitura-quixeramobim', '44555666000181', 'Recicla Quixeramobim LTDA', 'Recicla Quixeramobim',
        'empresa2@demo.com', '$2b$12$EewUZscvfTEMpkYELJXRruH5oYa4ztKO8qr7K34pqpwlQgUbGLCwG', 'APROVADA', 1);

INSERT OR IGNORE INTO usuarios_admin (id, id_prefeitura, nome, email, senha_hash, perfil)
VALUES ('gestor-demo', 'prefeitura-quixada', 'Gestor Demo', 'gestor@demo.com', '$2b$12$EewUZscvfTEMpkYELJXRruH5oYa4ztKO8qr7K34pqpwlQgUbGLCwG', 'GESTOR');

INSERT OR IGNORE INTO usuarios_admin (id, id_prefeitura, nome, email, senha_hash, perfil)
VALUES ('gestor-quixeramobim', 'prefeitura-quixeramobim', 'Gestor Quixeramobim', 'gestor2@demo.com', '$2b$12$EewUZscvfTEMpkYELJXRruH5oYa4ztKO8qr7K34pqpwlQgUbGLCwG', 'GESTOR');

