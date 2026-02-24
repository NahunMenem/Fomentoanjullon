from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import create_engine, Column, Integer, String, Date, Numeric, ForeignKey, DateTime, func
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, Session
from pydantic import BaseModel
from datetime import date
import os

# ==========================================================
# CONFIGURACIÓN DE BASE DE DATOS
# ==========================================================
# Railway inyecta automáticamente la variable DATABASE_URL.
# NO hardcodear la conexión en producción.

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise Exception("DATABASE_URL no está configurada")

# pool_pre_ping evita errores si la conexión se cae
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# ==========================================================
# INICIALIZACIÓN DE FASTAPI
# ==========================================================

app = FastAPI(title="Sistema de Gestión de Agua 🚰")


# ==========================================================
# MODELOS ORM (Representan las tablas en la base)
# ==========================================================

class Asociado(Base):
    """
    Tabla de asociados (clientes del servicio de agua)
    """
    __tablename__ = "asociados"

    id = Column(Integer, primary_key=True, index=True)
    codigo = Column(String(20), unique=True, nullable=False)
    nombre = Column(String(100), nullable=False)
    dni = Column(String(20), nullable=False)
    domicilio = Column(String(150), nullable=False)
    medidor = Column(String(30), unique=True, nullable=False)
    estado = Column(String(20), default="activo")
    fecha_alta = Column(Date, default=date.today)
    created_at = Column(DateTime, server_default=func.now())

    lecturas = relationship("Lectura", back_populates="asociado")
    pagos = relationship("PagoAgua", back_populates="asociado")


class Lectura(Base):
    """
    Tabla de lecturas mensuales de medidor
    """
    __tablename__ = "lecturas"

    id = Column(Integer, primary_key=True)
    asociado_id = Column(Integer, ForeignKey("asociados.id", ondelete="CASCADE"))
    periodo = Column(Date, nullable=False)
    lectura_anterior = Column(Integer, nullable=False)
    lectura_actual = Column(Integer, nullable=False)
    precio_por_m3 = Column(Numeric(10, 2), nullable=False)

    asociado = relationship("Asociado", back_populates="lecturas")


class PagoAgua(Base):
    """
    Tabla de pagos realizados por los asociados
    """
    __tablename__ = "pagos_agua"

    id = Column(Integer, primary_key=True)
    asociado_id = Column(Integer, ForeignKey("asociados.id", ondelete="CASCADE"))
    lectura_id = Column(Integer, ForeignKey("lecturas.id", ondelete="SET NULL"), nullable=True)
    fecha_pago = Column(Date, default=date.today)
    monto = Column(Numeric(12, 2), nullable=False)
    metodo_pago = Column(String(30))

    asociado = relationship("Asociado", back_populates="pagos")


# ==========================================================
# SCHEMAS (Validación de datos de entrada)
# ==========================================================

class AsociadoCreate(BaseModel):
    """
    Datos necesarios para crear un nuevo asociado
    """
    codigo: str
    nombre: str
    dni: str
    domicilio: str
    medidor: str


class LecturaCreate(BaseModel):
    """
    Datos necesarios para registrar una lectura mensual
    """
    asociado_id: int
    periodo: date
    lectura_anterior: int
    lectura_actual: int
    precio_por_m3: float


class PagoCreate(BaseModel):
    """
    Datos necesarios para registrar un pago
    """
    asociado_id: int
    lectura_id: int | None = None
    monto: float
    metodo_pago: str


# ==========================================================
# DEPENDENCIA DE BASE DE DATOS
# ==========================================================

def get_db():
    """
    Abre una sesión de base de datos
    y la cierra automáticamente al finalizar la request
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==========================================================
# EVENTO DE INICIO
# ==========================================================

@app.on_event("startup")
def startup():
    print("🚰 Sistema de Agua iniciado correctamente")


# ==========================================================
# ENDPOINTS
# ==========================================================

@app.get("/")
def home():
    """
    Endpoint de prueba para verificar que la API funciona
    """
    return {"mensaje": "Sistema Agua funcionando correctamente 🚰"}


# ----------------------------------------------------------
# CREAR ASOCIADO
# ----------------------------------------------------------

@app.post("/asociados")
def crear_asociado(data: AsociadoCreate, db: Session = Depends(get_db)):
    """
    Crea un nuevo asociado en el sistema.
    """
    asociado = Asociado(**data.dict())
    db.add(asociado)
    db.commit()
    db.refresh(asociado)
    return asociado


# ----------------------------------------------------------
# LISTAR ASOCIADOS
# ----------------------------------------------------------

@app.get("/asociados")
def listar_asociados(db: Session = Depends(get_db)):
    """
    Devuelve la lista completa de asociados.
    """
    return db.query(Asociado).all()


# ----------------------------------------------------------
# REGISTRAR LECTURA
# ----------------------------------------------------------

@app.post("/lecturas")
def cargar_lectura(data: LecturaCreate, db: Session = Depends(get_db)):
    """
    Registra una nueva lectura mensual.
    - Valida que la lectura actual no sea menor que la anterior.
    - Calcula consumo e importe.
    """

    if data.lectura_actual < data.lectura_anterior:
        raise HTTPException(status_code=400, detail="Lectura actual menor que la anterior")

    lectura = Lectura(**data.dict())
    db.add(lectura)
    db.commit()
    db.refresh(lectura)

    consumo = data.lectura_actual - data.lectura_anterior
    importe = consumo * data.precio_por_m3

    return {
        "lectura_id": lectura.id,
        "consumo_m3": consumo,
        "importe_calculado": importe
    }


# ----------------------------------------------------------
# REGISTRAR PAGO
# ----------------------------------------------------------

@app.post("/pagos")
def registrar_pago(data: PagoCreate, db: Session = Depends(get_db)):
    """
    Registra un pago realizado por un asociado.
    Puede vincularse opcionalmente a una lectura específica.
    """
    pago = PagoAgua(**data.dict())
    db.add(pago)
    db.commit()
    db.refresh(pago)
    return pago


# ----------------------------------------------------------
# CALCULAR DEUDA DE UN ASOCIADO
# ----------------------------------------------------------

@app.get("/deuda/{asociado_id}")
def calcular_deuda(asociado_id: int, db: Session = Depends(get_db)):
    """
    Calcula:
    - Total facturado (sumatoria de todas las lecturas)
    - Total pagado
    - Deuda actual
    """

    lecturas = db.query(Lectura).filter(Lectura.asociado_id == asociado_id).all()
    pagos = db.query(PagoAgua).filter(PagoAgua.asociado_id == asociado_id).all()

    total_facturado = sum(
        (l.lectura_actual - l.lectura_anterior) * float(l.precio_por_m3)
        for l in lecturas
    )

    total_pagado = sum(float(p.monto) for p in pagos)

    return {
        "total_facturado": total_facturado,
        "total_pagado": total_pagado,
        "deuda_actual": total_facturado - total_pagado
    }
