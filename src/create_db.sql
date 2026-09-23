CREATE TABLE IF NOT EXISTS prefeituras (
    id TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME
);

CREATE TABLE IF NOT EXISTS materiais (
    id TEXT PRIMARY KEY,
    categoria TEXT NOT NULL,
    fator_emissaoipcc REAL NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME
);

CREATE TABLE IF NOT EXISTS empresas (
    id TEXT PRIMARY KEY,
    prefeitura_id TEXT NOT NULL,
    cnpj TEXT UNIQUE NOT NULL,
    razao_social TEXT NOT NULL,
    nome_fantasia TEXT,
    email TEXT UNIQUE NOT NULL,
    telefone TEXT,
    endereco TEXT,
    pwd_hash TEXT NOT NULL,
    empresa_status TEXT DEFAULT 'AGUARDANDO_VALIDACAO' 
        CHECK(empresa_status IN ('AGUARDANDO_VALIDACAO', 'APROVADA', 'RECUSADA', 'DESASSOCIADA')),
    motivo_recusa TEXT,
    token_confirmacao_email TEXT,
    token_expiracao DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME,
    FOREIGN KEY (prefeitura_id) REFERENCES prefeituras(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS usuarios_admin (
    id TEXT PRIMARY KEY,
    id_prefeitura TEXT NOT NULL,
    nome TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    senha_hash TEXT NOT NULL,
    perfil TEXT DEFAULT 'GESTOR' 
        CHECK(perfil IN ('ADMIN', 'GESTOR', 'COMUM')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME,
    FOREIGN KEY (id_prefeitura) REFERENCES prefeituras(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS usuarios_empresa (
    id TEXT PRIMARY KEY,
    id_empresa TEXT NOT NULL,
    nome TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    senha_hash TEXT NOT NULL,
    perfil TEXT DEFAULT 'COMUM' 
        CHECK(perfil IN ('ADMIN', 'GESTOR', 'COMUM')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME,
    FOREIGN KEY (id_empresa) REFERENCES empresas(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS registros (
    id TEXT PRIMARY KEY,
    empresa_id TEXT NOT NULL,
    material_id TEXT NOT NULL,
    validador_id TEXT,
    criado_por_gestor_id TEXT,
    periodo TEXT NOT NULL,
    volume_total_original REAL NOT NULL,
    percentual_reciclado REAL NOT NULL,
    status_validacao TEXT DEFAULT 'PENDENTE' 
        CHECK(status_validacao IN ('PENDENTE', 'VALIDADO', 'REJEITADO')),
    motivo_rejeicao TEXT,
    volume_validado REAL,
    valorestimado REAL,
    carbonoevitado REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    deleted_at DATETIME,
    FOREIGN KEY (empresa_id) REFERENCES empresas(id) ON DELETE CASCADE,
    FOREIGN KEY (material_id) REFERENCES materiais(id),
    FOREIGN KEY (validador_id) REFERENCES usuarios_admin(id),
    FOREIGN KEY (criado_por_gestor_id) REFERENCES usuarios_admin(id)
);