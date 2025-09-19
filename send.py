#!/usr/bin/env python3
# scripts/send_invites.py

import os, ssl, smtplib, time, argparse, mimetypes, sys
from email.message import EmailMessage
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models import Member  

# --- Config DB
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cousinade.db")

# --- Config SMTP (via variables d'environnement)
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))        # TLS
SMTP_USER = os.getenv("SMTP_USER", 'david.guessab@gmail.com')
SMTP_PASS = os.getenv("SMTP_PASS", 'twtzcjudfajpizjp')
FROM_NAME = os.getenv("FROM_NAME", "David")
REPLY_TO  = os.getenv("REPLY_TO", SMTP_USER or "")

# --- Templating ultra simple {first_name} {last_name} {email} {site_url}
SITE_URL = os.getenv("SITE_URL", "https://cousi2026.oatipi.com")

def load_body(path: str) -> tuple[str, str]:
    if not os.path.exists(path):
        print(f"Fichier corps introuvable: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    ext = os.path.splitext(path)[1].lower()
    if ext in [".html", ".htm"]:
        return content, "html"
    return content, "plain"

def personalize(s: str, m: Member) -> str:
    data = {
        "first_name": m.first_name or "",
        "last_name": m.last_name or "",
        "email": (m.email or "").lower(),
        "site_url": SITE_URL,
    }
    try:
        return s.format(**data)
    except KeyError:
        # si le template contient une clé inconnue, on ne casse pas l'envoi
        return s

def collect_recipients(session) -> list[Member]:
    # Tous les membres avec email non vide
    emails_seen = set()
    recipients = []
    for m in session.scalars(select(Member).where(Member.email.isnot(None))):
        em = (m.email or "").strip().lower()
        if not em:
            continue
        if em in emails_seen:
            continue
        emails_seen.add(em)
        recipients.append(m)
    return recipients

def send_one(smtp: smtplib.SMTP, m: Member, subject_t: str, body_t: str, body_type: str):
    msg = EmailMessage()
    sender = f"{FROM_NAME} <{SMTP_USER}>" if FROM_NAME and SMTP_USER else (SMTP_USER or "no-reply@example.org")
    msg["From"] = sender
    msg["To"] = (m.email or "").strip()
    if REPLY_TO:
        msg["Reply-To"] = REPLY_TO

    subject = personalize(subject_t, m)
    body = personalize(body_t, m)
    msg["Subject"] = subject

    if body_type == "html":
        msg.set_content("Version HTML requise. Ouvrez ce message dans un client compatible.")
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)

    smtp.send_message(msg)

def main():
    parser = argparse.ArgumentParser(description="Envoyer un email à tous les membres avec email.")
    parser.add_argument("-s", "--subject", required=True, help="Sujet de l'email (supports {first_name} {last_name} {site_url})")
    parser.add_argument("-b", "--body", required=True, help="Fichier texte/HTML du corps (supports {first_name} {last_name} {site_url})")
    parser.add_argument("--dry-run", action="store_true", help="N'envoie rien, affiche seulement la liste.")
    parser.add_argument("--limit", type=int, default=0, help="Limiter le nombre d'envois (0 = illimité)")
    parser.add_argument("--sleep", type=float, default=0.6, help="Pause en secondes entre emails (anti-spam)")
    args = parser.parse_args()

    # Sanity SMTP
    if not args.dry_run and (not SMTP_USER or not SMTP_PASS):
        print("Erreur: définissez SMTP_USER et SMTP_PASS (App Password Gmail recommandé).", file=sys.stderr)
        sys.exit(2)

    # Charger corps
    body, body_type = load_body(args.body)

    # DB
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as db:
        recips = collect_recipients(db)
        if args.limit and args.limit > 0:
            recips = recips[:args.limit]

        print(f"{len(recips)} destinataire(s) trouvé(s).")

        if args.dry_run:
            for m in recips:
                print(f"- {m.first_name} {m.last_name} <{m.email}>")
            return

        # SMTP TLS
        context = ssl.create_default_context()
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.login(SMTP_USER, SMTP_PASS)

            sent = 0
            for m in recips:
                try:
                    send_one(smtp, m, args.subject, body, body_type)
                    sent += 1
                    print(f"OK  {m.email}")
                except Exception as e:
                    print(f"ERR {m.email}: {e}", file=sys.stderr)
                time.sleep(args.sleep)

        print(f"Terminé. {sent}/{len(recips)} envoyé(s).")

if __name__ == "__main__":
    main()
