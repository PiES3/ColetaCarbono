import os
import smtplib
from email.message import EmailMessage

from loguru import logger

SMTP_TIMEOUT_SEGUNDOS = 10
PORTA_SMTP_SSL = 465


def _starttls_ativo() -> bool:
    valor = os.getenv("SMTP_STARTTLS", "true").strip().lower()
    return valor not in ("0", "false", "no", "nao", "não", "off")


class EmailService:
    def enviar(self, destinatario: str, assunto: str, corpo: str) -> bool:
        """
        Envia um e-mail de texto pelo servidor SMTP configurado no ambiente.
        Sem SMTP_HOST, apenas registra a mensagem no log (uso em desenvolvimento).
        Retorna False quando o envio falha, sem interromper a requisição.
        """
        host = os.getenv("SMTP_HOST")
        if not host:
            logger.info(
                f"[EmailService] Para: {destinatario} | Assunto: {assunto}\n{corpo}"
            )
            return True

        porta = int(os.getenv("SMTP_PORT", "587"))
        usuario = os.getenv("SMTP_USER")

        mensagem = EmailMessage()
        mensagem["From"] = os.getenv("SMTP_FROM") or usuario or "nao-responda@arclear"
        mensagem["To"] = destinatario
        mensagem["Subject"] = assunto
        mensagem.set_content(corpo)

        try:
            if porta == PORTA_SMTP_SSL:
                conexao = smtplib.SMTP_SSL(host, porta, timeout=SMTP_TIMEOUT_SEGUNDOS)
            else:
                conexao = smtplib.SMTP(host, porta, timeout=SMTP_TIMEOUT_SEGUNDOS)
            with conexao as servidor:
                if porta != PORTA_SMTP_SSL and _starttls_ativo():
                    servidor.starttls()
                if usuario:
                    servidor.login(usuario, os.getenv("SMTP_PASSWORD", ""))
                servidor.send_message(mensagem)
        except (OSError, smtplib.SMTPException) as erro:
            logger.error(f"[EmailService] Falha ao enviar para {destinatario}: {erro}")
            return False

        return True


email_service = EmailService()
