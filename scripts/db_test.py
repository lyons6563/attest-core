import psycopg2

conn = psycopg2.connect(
    dbname="decision_engine",
    user="postgres",
    password="postgres",
    host="localhost",
    port="5432"
)

cur = conn.cursor()
cur.execute("SELECT 1;")
print(cur.fetchone())

conn.close()

