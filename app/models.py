# app/models.py
from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Date, DateTime, Boolean, ForeignKey, UniqueConstraint, Text
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class Member(Base):
    __tablename__ = "members"
    id = Column(Integer, primary_key=True)
    # Données de base
    first_name = Column(String(80), nullable=False)
    last_name = Column(String(80), nullable=False)
    birth_date = Column(Date, nullable=True)
    email = Column(String(255), nullable=True, unique=False)
    phone = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    # Métadonnées
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Confort d'affichage
    family_branch = Column(String(80), nullable=True)  # branche/ancêtre si utile

    # Relations
    parents = relationship(
        "ParentChild", foreign_keys="ParentChild.child_id",
        back_populates="child", cascade="all, delete-orphan"
    )
    children_links = relationship(
        "ParentChild", foreign_keys="ParentChild.parent_id",
        back_populates="parent", cascade="all, delete-orphan"
    )
    couples_a = relationship("Couple", foreign_keys="Couple.partner_a_id",
                             back_populates="partner_a", cascade="all, delete-orphan")
    couples_b = relationship("Couple", foreign_keys="Couple.partner_b_id",
                             back_populates="partner_b", cascade="all, delete-orphan")

class ParentChild(Base):
    __tablename__ = "parent_child"
    id = Column(Integer, primary_key=True)
    parent_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    child_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    __table_args__ = (UniqueConstraint('parent_id', 'child_id', name='uq_parent_child'),)
    parent = relationship("Member", foreign_keys=[parent_id], back_populates="children_links")
    child = relationship("Member", foreign_keys=[child_id], back_populates="parents")

class Couple(Base):
    __tablename__ = "couples"
    id = Column(Integer, primary_key=True)
    partner_a_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    partner_b_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    status = Column(String(30), default="current")  # current | separated | widowed
    __table_args__ = (UniqueConstraint('partner_a_id', 'partner_b_id', name='uq_couple_pair'),)
    partner_a = relationship("Member", foreign_keys=[partner_a_id], back_populates="couples_a")
    partner_b = relationship("Member", foreign_keys=[partner_b_id], back_populates="couples_b")

class EventWeekend(Base):
    __tablename__ = "event_weekends"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    slots = relationship("EventSlot", back_populates="weekend", cascade="all, delete-orphan")

class EventSlot(Base):
    __tablename__ = "event_slots"
    id = Column(Integer, primary_key=True)
    weekend_id = Column(Integer, ForeignKey("event_weekends.id"), nullable=False)
    date = Column(Date, nullable=False)           # 2026-05-01, etc.
    label = Column(String(40), nullable=False)    # "Vendredi soir", "Samedi midi", ...
    order_index = Column(Integer, default=0)      # pour l’ordre d’affichage
    weekend = relationship("EventWeekend", back_populates="slots")

class PersonAttendance(Base):
    __tablename__ = "person_attendance"
    id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("members.id"), nullable=False)
    slot_id = Column(Integer, ForeignKey("event_slots.id"), nullable=False)
    present = Column(Boolean, default=True, nullable=False)  # on garde True/False (ou bien on ne stocke que True)
    __table_args__ = (UniqueConstraint('person_id', 'slot_id', name='uq_person_slot'),)

    person = relationship("Member")
    slot = relationship("EventSlot")