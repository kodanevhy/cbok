"""Useful db-related constants. In their own file so they can be imported
cleanly."""

# The maximum value a signed INT type may have
MAX_INT = 0x7FFFFFFF

# NOTE(kodanevhy): This is supposed to represent the maximum value that we can
# place into a SQL single precision float so that we can check whether values
# are oversize. Postgres and MySQL both define this as their max whereas Sqlite
# uses dynamic typing so this would not apply. Different dbs react in different
# ways to oversize values e.g. postgres will raise an exception while mysql
# will round off the value. Nevertheless we may still want to know prior to
# insert whether the value is oversize or not.
SQL_SP_FLOAT_MAX = 3.40282e+38
