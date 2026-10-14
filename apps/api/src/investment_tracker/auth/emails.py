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
