from database import DatabaseManager
db = DatabaseManager()
db.add_or_update_tracking('DUMMY-ITEM', '1234567890', 'jne', 'Jakarta')
print("Data dummy berhasil ditambahkan.")
