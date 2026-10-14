from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import config


class Base(DeclarativeBase):
    pass


engine = create_engine(config().database_url, pool_pre_ping=True,
                       connect_args={'check_same_thread': False, 'timeout': 30}
                       if config().database_url.startswith('sqlite') else {})
if engine.dialect.name == 'sqlite':
    @event.listens_for(engine, 'connect')
    def sqlite_pragmas(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA journal_mode=WAL')

Session = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def transaction():
    with Session() as db:
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


def get_db():
    with Session() as db:
        yield db
