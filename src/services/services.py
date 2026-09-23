import requests
from sqlalchemy.orm import Session
from fastapi import HTTPException

from src.models.models import Material, Registro
from src.schemas.enums import StatusValidacao

# valor medio da tonelada de co2 em dol (o valor varia em um intervalo mt grande).
VALOR_TONELADA_CO2_USD = 5.0

def obter_cotacao_dolar() -> float:
    try:
        response = requests.get("https://economia.awesomeapi.com.br/last/USD-BRL")
        response.raise_for_status()
        dados = response.json()
        return float(dados["USDBRL"]["bid"])
    except Exception:
        return 5.30 ## valor padrão caso a API falhe (decidir com o time)

class RegistroService:
    def validar_e_calcular(
        self, 
        db: Session, 
        registro_id: str, 
        validador_id: str, 
        volume_validado: float
    ) -> Registro:
        
        # 1. Busca o registro diretamente usando a sessão do SQLAlchemy
        registro = db.query(Registro).filter(Registro.id == registro_id).first()
        if not registro:
            raise HTTPException(status_code=404, detail="Registro não encontrado")
            
        if registro.status_validacao != StatusValidacao.PENDENTE:
            raise HTTPException(status_code=400, detail="Registro já processado")

        # 2. Busca o material vinculado diretamente
        material = db.query(Material).filter(Material.id == registro.material_id).first()
        if not material:
            raise HTTPException(status_code=404, detail="Material não encontrado")

        # 3. Regra de Negócio: Cálculo do Carbono Evitado
        carbono_evitado = volume_validado * (registro.percentual_reciclado / 100) * material.fator_emissaoipcc

        # 4. Regra de Negócio: Conversão Monetária estimada
        cotacao_atual = obter_cotacao_dolar()
        valor_estimado_brl = carbono_evitado * VALOR_TONELADA_CO2_USD * cotacao_atual

        # 5. Atualiza os atributos diretamente na instância do modelo
        registro.validador_id = validador_id
        registro.volume_validado = volume_validado
        registro.status_validacao = StatusValidacao.VALIDADO
        registro.carbonoevitado = carbono_evitado
        registro.valorestimado = round(valor_estimado_brl, 2)
        
        # 6. Efetiva as alterações no banco de dados e atualiza o objeto
        db.commit()
        db.refresh(registro)
        
        return registro

registro_service = RegistroService()