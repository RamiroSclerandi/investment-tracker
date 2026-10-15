from datetime import timedelta

from investment_tracker.core.email import EmailMessage


def verification_email(
    *, to: str, display_name: str, web_base_url: str, raw_token: str
) -> EmailMessage:
    # The token rides in the fragment so it never reaches server or proxy logs.
    link = f"{web_base_url}/verify-email#token={raw_token}"
    text = (
        f"Hola {display_name},\n\n"
        "Para activar tu cuenta de Investment Tracker, abrí este enlace dentro de las "
        f"próximas 24 horas:\n\n{link}\n\n"
        "Si no creaste una cuenta, ignorá este mensaje.\n"
    )
    return EmailMessage(to=to, subject="Verificá tu email", text=text)


def password_reset_email(
    *, to: str, display_name: str, web_base_url: str, raw_token: str, ttl: timedelta
) -> EmailMessage:
    link = f"{web_base_url}/reset-password#token={raw_token}"
    minutes = int(ttl.total_seconds() // 60)
    text = (
        f"Hola {display_name},\n\n"
        "Para elegir una nueva contraseña de Investment Tracker, abrí este enlace dentro de "
        f"los próximos {minutes} minutos:\n\n{link}\n\n"
        "Si no lo pediste, ignorá este mensaje: tu contraseña no cambia.\n"
    )
    return EmailMessage(to=to, subject="Restablecé tu contraseña", text=text)
