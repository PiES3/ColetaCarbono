import requests
from sqlalchemy.orm import Session
from fastapi import HTTPException
from src.repositories.registro import registro_repo
from src.repositories.base import BaseRepository 
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
        
        # 1. Busca o registro e valida se existe
        registro = registro_repo.get_by_id(db, id=registro_id)
        if not registro:
            raise HTTPException(status_code=404, detail="Registro não encontrado")
            
        if registro.status_validacao != StatusValidacao.PENDENTE:
            raise HTTPException(status_code=400, detail="Registro já processado")

        # 2. Busca o fator de emissão do material vinculado
        material_repo = BaseRepository(Material)
        material = material_repo.get_by_id(db, id=registro.material_id)
        if not material:
            raise HTTPException(status_code=404, detail="Material não encontrado")

        # 3. Regra de Negócio: Cálculo do Carbono Evitado
        # Toneladas validadas * Fator IPCC do material
        carbono_evitado = volume_validado * material.fator_emissaoipcc

        # 4. Regra de Negócio: Conversão Monetária
        cotacao_atual = obter_cotacao_dolar()
        valor_estimado_brl = carbono_evitado * VALOR_TONELADA_CO2_USD * cotacao_atual

        # 5. Atualiza a transação com os valores definitivos
        dados_atualizacao = {
            "validador_id": validador_id,
            "volume_validado": volume_validado,
            "status_validacao": StatusValidacao.VALIDADO,
            "carbonoevitado": carbono_evitado,
            "valorestimado": round(valor_estimado_brl, 2)
        }
        
        return registro_repo.update(db, db_obj=registro, obj_in=dados_atualizacao)

registro_service = RegistroService()