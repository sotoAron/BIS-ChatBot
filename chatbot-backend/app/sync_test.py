import asyncio
import os
import sys

sys.path.append("/app")
from app.rag.moodle_sync import sync_all_course_documents

async def main():
    print("Iniciando sincronización del curso 2...")
    stats = await sync_all_course_documents(2, "2026", "ISI")
    print(f"Resultado: {stats}")

if __name__ == "__main__":
    asyncio.run(main())
