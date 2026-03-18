__version__ = "0.3"

try:
    import pymysql
except ModuleNotFoundError:
    pymysql = None

if pymysql is not None:
    pymysql.version_info = (2, 2, 1, "final", 0)
    pymysql.install_as_MySQLdb()
