# app/main.py

import secrets, datetime, json, os
from datetime import date

from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker, Session
from jinja2 import Environment, FileSystemLoader, select_autoescape
from .models import Base, Member, ParentChild, Couple, EventWeekend, EventSlot, PersonAttendance

from fastapi import FastAPI, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware


def create_app() -> FastAPI:
    app = FastAPI()

    # 1) Session d'abord
    SECRET_KEY = os.getenv("SESSION_SECRET", secrets.token_hex(32))
    app.add_middleware(
        SessionMiddleware,
        secret_key=SECRET_KEY,
        same_site="lax",
        session_cookie="cousinade_session",
    )

    # 2) Static (même app)
    app.mount("/static", StaticFiles(directory="static"), name="static")
    return app

app = create_app()

DATABASE_URL = "sqlite:///./cousinade.db"  # passe à Postgres si besoin
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(bind=engine)
templates = Environment(loader=FileSystemLoader("templates"), autoescape=select_autoescape(['html', 'xml']))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session) -> Member | None:
    uid = request.session.get("user_member_id")
    return db.get(Member, uid) if uid else None


# ---- Annuaire
@app.get("/", response_class=HTMLResponse)
def directory(request: Request, q: str | None = None, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user : 
        return RedirectResponse(url="/login", status_code=303)
    
    stmt = select(Member) #where( (Member.family_branch == 'cousin') )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (Member.first_name.ilike(like)) |
            (Member.last_name.ilike(like))
        )
    members = db.scalars(stmt.order_by(Member.last_name, Member.first_name)).all()
    tpl = templates.get_template("directory.html")
    return tpl.render(request=request, members=members, q=q or "", user=user)


# ---- Fiche
@app.get("/member/{member_id}", response_class=HTMLResponse)
def member_card(request: Request, member_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user : 
        return RedirectResponse(url="/login", status_code=303)

    m = db.get(Member, member_id)
    if not m:
        raise HTTPException(404, "Membre introuvable")
    # enfants pour affichage
    children = [lnk.child for lnk in m.children_links]
    partners = {*(c.partner_a if c.partner_a_id != m.id else c.partner_b for c in (m.couples_a + m.couples_b))}
    tpl = templates.get_template("member.html")
    return tpl.render(request=request, m=m, children=children, partners=partners, user=user)

# ---- Edition via lien sécurisé
@app.get("/edit", response_class=HTMLResponse)
def edit_form(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user : 
        return RedirectResponse(url="/login", status_code=303)

    owner = user
    # foyer = propriétaire + conjoint(s) + enfants
    partners = {*(c.partner_a if c.partner_a_id != owner.id else c.partner_b for c in (owner.couples_a + owner.couples_b))}
    children = [lnk.child for lnk in owner.children_links]
    tpl = templates.get_template("edit.html")
    return tpl.render(request=request, owner=owner, partners=list(partners), children=children, user=user)

@app.post("/edit/save")
def save_form(request: Request, owner_id: int = Form(...), family_json: str = Form(None),  db: Session = Depends(get_db),):
    user = get_current_user(request, db)
    if not user : 
        return RedirectResponse(url="/login", status_code=303)

    if family_json:
        data = json.loads(family_json)
        # --- 1) upsert membres
        def upsert_member(mobj):
            mid = mobj.get("id")
            is_new = mid is not None and mid < 0
            if is_new:
                m = Member(first_name=mobj.get("first_name") or "", last_name=mobj.get("last_name") or "")
                db.add(m); db.flush()
                mobj["id"] = m.id  # remappe l'id temporaire
            else:
                m = db.get(Member, mid)
                if not m:
                    m = Member(first_name=mobj.get("first_name") or "", last_name=mobj.get("last_name") or "")
                    db.add(m); db.flush()
                    mobj["id"] = m.id
            # champs de base
            m.first_name = (mobj.get("first_name") or m.first_name).strip()
            m.last_name  = (mobj.get("last_name")  or m.last_name).strip()
            m.email      = mobj.get("email")
            m.phone      = mobj.get("phone")
            m.address    = mobj.get("address")
            m.postal_code = mobj.get("postal_code")
            m.city       = mobj.get("city")
            bd = mobj.get("birth_date")
            if bd:
                try: m.birth_date = datetime.date.fromisoformat(bd)
                except ValueError: pass
            return m

        owner = upsert_member(data["owner"])
        partner_map = {}
        for p in data.get("partners", []):
            partner_map[p["id"]] = upsert_member(p)

        child_map = {}
        for c in data.get("children", []):
            child_map[c["id"]] = upsert_member(c)

        db.flush()

        # --- 2) Couplers (owner <-> partner)
        for p in data.get("partners", []):
            pid = partner_map[p["id"]].id
            exists = db.scalar(
                select(Couple).where(
                    ((Couple.partner_a_id==owner.id) & (Couple.partner_b_id==pid)) |
                    ((Couple.partner_a_id==pid) & (Couple.partner_b_id==owner.id))
                )
            )
            if not exists:
                db.add(Couple(partner_a_id=owner.id, partner_b_id=pid, status=p.get("couple_status","current")))
            else:
                exists.status = p.get("couple_status","current")

        # --- 3) Liens parent->enfant
        def ensure_parent_child(pid, cid):
            if not db.scalar(select(ParentChild).where(ParentChild.parent_id==pid, ParentChild.child_id==cid)):
                db.add(ParentChild(parent_id=pid, child_id=cid))

        for link in data.get("parent_child", []):
            # remap ids temporaires
            parent_id = partner_map.get(link["parent_id"], child_map.get(link["parent_id"], None)).id if link["parent_id"] < 0 else link["parent_id"]
            child_id  = child_map.get(link["child_id"], None).id if link["child_id"] < 0 else link["child_id"]
            if parent_id < 0: parent_id = owner.id  # fallback
            if link["parent_id"] == data["owner"]["id"]: parent_id = owner.id
            ensure_parent_child(parent_id, child_id)

        db.commit()

        return RedirectResponse(url=f"/member/{owner.id}", status_code=303)
    

# ---- Login: afficher le formulaire
@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    tpl = templates.get_template("login.html")
    return tpl.render(request=request, error=None)

# ---- Login: traiter l'email
@app.post("/login", response_class=HTMLResponse)
def do_login(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    email_norm = (email or "").strip().lower()
    if not email_norm:
        tpl = templates.get_template("login.html")
        return tpl.render(request=request, error="Merci d'indiquer votre email.")

    # On cherche un membre avec cet email (insensible à la casse)
    m = db.scalar(select(Member).where(Member.email.ilike(email_norm)))
    if not m:
        tpl = templates.get_template("login.html")
        return tpl.render(request=request, error="Adresse introuvable dans l'annuaire.")
    # OK: on met en session
    request.session["user_member_id"] = m.id
    return RedirectResponse(url="/", status_code=303)

# ---- Logout
@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


# ---- Admin : créer un token d’édition
@app.post("/admin/new-token")
def new_token(member_id: int, hours_valid: int = 72, db: Session = Depends(get_db)):
    token = secrets.token_urlsafe(32)
    t = EditToken(
        token=token,
        owner_member_id=member_id,
        expires_at=datetime.datetime.utcnow() + datetime.timedelta(hours=hours_valid)
    )
    db.add(t); db.commit()
    return {"edit_link": f"/edit?token={token}"}



def get_household(user: Member) -> list[Member]:
    # Conjoint(s) status=current
    partners = []
    for c in (user.couples_a + user.couples_b):
        if c.status == "current":
            partners.append(c.partner_b if c.partner_a_id == user.id else c.partner_a)
    # Enfants (liens parent->enfant)
    children = [lnk.child for lnk in user.children_links]
    # Déduplique et ordonne
    seen, members = set(), []
    for p in [user, *partners, *children]:
        if p and p.id not in seen:
            seen.add(p.id)
            members.append(p)
    return members


def ensure_rsvp_seed(db: Session):
    existing = db.scalar(select(func.count(EventSlot.id)))
    if existing and existing > 0:
        return

    # Week-end 1 : 1–3 mai 2026
    w1 = EventWeekend(name="Week-end 1 (1–3 mai 2026)", start_date=date(2026,5,1), end_date=date(2026,5,3))
    db.add(w1); db.flush()
    w1_slots = [
        (date(2026,5,1), "Vendredi soir"),
        (date(2026,5,2), "Samedi midi"),
        (date(2026,5,2), "Samedi soir"),
        (date(2026,5,3), "Dimanche midi"),
    ]
    for idx, (d, lbl) in enumerate(w1_slots):
        db.add(EventSlot(weekend_id=w1.id, date=d, label=lbl, order_index=idx))

    # Week-end 2 : 8–10 mai 2026
    w2 = EventWeekend(name="Week-end 2 (8–10 mai 2026)", start_date=date(2026,5,8), end_date=date(2026,5,10))
    db.add(w2); db.flush()
    w2_slots = [
        (date(2026,5,8), "Vendredi soir"),
        (date(2026,5,9), "Samedi midi"),
        (date(2026,5,9), "Samedi soir"),
        (date(2026,5,10), "Dimanche midi"),
    ]
    for idx, (d, lbl) in enumerate(w2_slots):
        db.add(EventSlot(weekend_id=w2.id, date=d, label=lbl, order_index=idx))

    db.commit()

# Page RSVP
@app.get("/rsvp", response_class=HTMLResponse)
def rsvp_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    ensure_rsvp_seed(db)

    # Foyer
    household = get_household(user)

    # Week-ends et slots
    weekends = db.scalars(select(EventWeekend).order_by(EventWeekend.start_date)).all()
    weekend_blocks = []
    for w in weekends:
        slots = db.scalars(select(EventSlot)
                           .where(EventSlot.weekend_id==w.id)
                           .order_by(EventSlot.order_index, EventSlot.id)).all()
        weekend_blocks.append({"id": w.id, "name": w.name, "slots": slots})

    # Présences existantes pour pré-cocher
    pa = db.scalars(select(PersonAttendance)
                    .where(PersonAttendance.person_id.in_([m.id for m in household]))).all()
    present_map = {(a.person_id, a.slot_id): a.present for a in pa}

    # Totaux globaux par slot (tous foyers confondus)
    totals = dict(db.execute(
        select(PersonAttendance.slot_id, func.sum(func.cast(PersonAttendance.present, Integer)))
        .group_by(PersonAttendance.slot_id)
    ).all()) if db.bind.dialect.name != "sqlite" else dict(db.execute(
        select(PersonAttendance.slot_id, func.sum(PersonAttendance.present*1)).group_by(PersonAttendance.slot_id)
    ).all())

    household_ids = [m.id for m in household]

    # Toutes présences des autres
    pa_others = db.scalars(
        select(PersonAttendance).where(PersonAttendance.person_id.not_in(household_ids))
    ).all()
    others_present = {(a.person_id, a.slot_id) for a in pa_others}

    # Indice slots par week-end
    slots_by_weekend = {w.id: db.scalars(
        select(EventSlot).where(EventSlot.weekend_id==w.id).order_by(EventSlot.order_index, EventSlot.id)
    ).all() for w in weekends}

    # Membres ayant répondu par week-end
    others_by_weekend = {}
    for w in weekends:
        slot_ids = {s.id for s in slots_by_weekend[w.id]}
        pids = {a.person_id for a in pa_others if a.slot_id in slot_ids}
        if pids:
            members = db.scalars(select(Member).where(Member.id.in_(list(pids))).order_by(Member.id)).all()
            others_by_weekend[w.id] = {"members": members}
        else:
            others_by_weekend[w.id] = {"members": []}

    # On rend
    tpl = templates.get_template("rsvp.html")
    return tpl.render(request=request,
                      user=user,
                      household=household,
                      weekends=weekend_blocks,
                      present_map=present_map,
                      totals=totals,
                      others_present=others_present, 
                      others_by_weekend=others_by_weekend)




@app.post("/rsvp/save")
async def rsvp_save(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    ensure_rsvp_seed(db)

    household = get_household(user)
    person_ids = [m.id for m in household]
    slots = db.scalars(select(EventSlot)).all()
    form = await request.form()

    # Pour chaque (person, slot) : coche = présent
    for pid in person_ids:
        for s in slots:
            key = f"p_{pid}_{s.id}"
            checked = key in form  # HTML envoie la clé si cochée
            att = db.scalar(select(PersonAttendance)
                            .where(PersonAttendance.person_id==pid, PersonAttendance.slot_id==s.id))
            if checked:
                if not att:
                    db.add(PersonAttendance(person_id=pid, slot_id=s.id, present=True))
                else:
                    att.present = True
            else:
                if att:
                    # soit on met False, soit on supprime — je supprime pour alléger
                    db.delete(att)

    db.commit()
    return RedirectResponse(url="/rsvp", status_code=status.HTTP_303_SEE_OTHER)



"""

# Petit helper pour lire vite les champs POST sans dépendance spécifique
from fastapi import Body
from starlette.datastructures import FormData

async def _read_form(request: Request) -> FormData:
    # FastAPI parse automatiquement si on l'appelle une fois
    return await request.form()

_form_cache_key = "_cached_form_"

async def await_request_form_value(request: Request, key: str):
    # mise en cache du parse
    if not hasattr(request.state, _form_cache_key):
        setattr(request.state, _form_cache_key, await _read_form(request))
    form = getattr(request.state, _form_cache_key)
    return form.get(key, None)"""
