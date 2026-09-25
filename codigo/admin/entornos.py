# -*- coding: utf-8 -*-
"""Bloque B - Entornos.

EL DEFECTO QUE CORRIGE. En el sistema, `POST /environments` asigna el entorno a
quien lo crea: pone `teacher_id = usuario actual` y ademas reescribe el
`environment_id` de ese usuario. Un administrador que cree un entorno se lo
asigna a si mismo y pierde el suyo anterior. Por eso hoy el administrador no
puede montar el curso de otro.

Aqui el entorno se crea PARA un docente, que se elige, y el administrador no
queda tocado.

LAS DOS PUNTAS, Y UNA EXCEPCION. La relacion vive en dos sitios:
`environments.teacher_id` y `users.environment_id`. Escribir solo una deja al
docente sin acceso a su propio entorno o con acceso a uno ajeno, asi que las
operaciones de aqui actualizan las dos.

La excepcion es el ADMINISTRADOR: queda como responsable del entorno, pero no
recibe `environment_id`. Su acceso es transversal por rol, y atarlo a un entorno
concreto lo dejaria apuntando al ultimo curso que hubiera tocado -que es
exactamente el defecto del sistema que este modulo corrige-.
"""
import contexto
import registro


class ErrorEntorno(Exception):
    pass


def lista_entornos(s):
    """B3 - Entornos con su docente y cuantos documentos tiene su corpus."""
    User, _, Environment, _ = contexto.modelos()
    from app.models.corpus_metadata import CorpusMetadata

    salida = []
    for e in s.query(Environment).order_by(Environment.created_at).all():
        docente = s.query(User).filter(User.id == e.teacher_id).first()
        documentos = (
            s.query(CorpusMetadata)
            .filter(CorpusMetadata.environment_id == e.id)
            .filter(CorpusMetadata.status != "eliminado")
            .count()
        )
        estudiantes = s.query(User).filter(User.environment_id == e.id).filter(User.role == "student").count()
        salida.append({
            "id": e.id,
            "nombre": e.name,
            "estado": e.status.value if hasattr(e.status, "value") else str(e.status),
            "docente": docente.email if docente else "(sin docente)",
            "docente_id": e.teacher_id,
            "documentos": documentos,
            "estudiantes": estudiantes,
        })
    return salida


def crea_entorno(s, nombre, teacher_id, descripcion=None, area=None, nivel=None, publicado=True):
    """B1 - Crea un entorno para un docente concreto y se lo asigna."""
    User, UserRole, Environment, EnvironmentStatus = contexto.modelos()

    if not nombre or not nombre.strip():
        raise ErrorEntorno("El entorno necesita un nombre")

    docente = s.query(User).filter(User.id == teacher_id).first()
    if not docente:
        raise ErrorEntorno("No existe la cuenta indicada como docente")
    if docente.role not in (UserRole.teacher, UserRole.admin):
        raise ErrorEntorno("La cuenta %s no es docente ni administrador" % docente.email)

    entorno = Environment(
        teacher_id=docente.id,
        name=nombre.strip(),
        description=(descripcion or None),
        knowledge_area=(area or None),
        education_level=(nivel or None),
        status=EnvironmentStatus.published if publicado else EnvironmentStatus.draft,
    )
    s.add(entorno)
    s.flush()

    # La otra punta: el docente queda apuntando a su entorno. El administrador
    # NO: su acceso es transversal, y darle un environment_id lo ataria al ultimo
    # curso que hubiera creado, que es justo el defecto del sistema que este
    # modulo corrige.
    if docente.role == UserRole.teacher:
        docente.environment_id = entorno.id
    s.commit()
    s.refresh(entorno)

    registro.anota("crear_entorno", {"entorno": entorno.id, "nombre": entorno.name,
                                     "docente": docente.email})
    return entorno


def reasigna_docente(s, environment_id, nuevo_teacher_id, liberar_anterior=True):
    """B2 - Cambia el docente de un entorno, actualizando las dos puntas.

    Al docente anterior se le retira el entorno si apuntaba a este, para que no
    conserve acceso a un curso que ya no es suyo. Es lo predeterminado, y se
    puede desactivar cuando se quiera dejar a los dos con acceso.
    """
    User, UserRole, Environment, _ = contexto.modelos()

    entorno = s.query(Environment).filter(Environment.id == environment_id).first()
    if not entorno:
        raise ErrorEntorno("No existe el entorno indicado")

    nuevo = s.query(User).filter(User.id == nuevo_teacher_id).first()
    if not nuevo:
        raise ErrorEntorno("No existe la cuenta indicada como docente")
    if nuevo.role not in (UserRole.teacher, UserRole.admin):
        raise ErrorEntorno("La cuenta %s no es docente ni administrador" % nuevo.email)

    anterior = s.query(User).filter(User.id == entorno.teacher_id).first()

    entorno.teacher_id = nuevo.id
    if nuevo.role == UserRole.teacher:
        nuevo.environment_id = entorno.id
    if liberar_anterior and anterior and anterior.id != nuevo.id and anterior.environment_id == entorno.id:
        anterior.environment_id = None

    s.commit()
    registro.anota("reasignar_docente", {
        "entorno": entorno.id,
        "anterior": anterior.email if anterior else None,
        "nuevo": nuevo.email,
        "anterior_liberado": bool(liberar_anterior and anterior and anterior.id != nuevo.id),
    })
    return entorno


def docentes_disponibles(s):
    """Cuentas que pueden ser docente de un entorno, para elegir de una lista."""
    User, UserRole, _, _ = contexto.modelos()
    return (
        s.query(User)
        .filter(User.role.in_([UserRole.teacher, UserRole.admin]))
        .order_by(User.email)
        .all()
    )
