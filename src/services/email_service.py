import os
import smtplib
from email.message import EmailMessage

from loguru import logger


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
            if porta == 465:
                conexao = smtplib.SMTP_SSL(host, porta, timeout=10)
            else:
                conexao = smtplib.SMTP(host, porta, timeout=10)
            with conexao as servidor:
                if porta != 465 and os.getenv("SMTP_STARTTLS", "true") != "false":
                    servidor.starttls()
                if usuario:
                    servidor.login(usuario, os.getenv("SMTP_PASSWORD", ""))
                servidor.send_message(mensagem)
        except (OSError, smtplib.SMTPException) as erro:
            logger.error(f"[EmailService] Falha ao enviar para {destinatario}: {erro}")
            return False

        return True


email_service = EmailService()
