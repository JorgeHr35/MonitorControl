import asyncio
from aiowebostv import WebOsClient

async def probar_lg():
    ip_tv = "192.168.68.104"
    print(f"Conectando a {ip_tv} con aiowebostv...")
    
    client = WebOsClient(ip_tv)
    
    try:
        print("MIRA LA PANTALLA DE LA TV Y ACEPTA EL MENSAJE...")
        await client.connect()
        print("¡Conexión exitosa y emparejada!")
        
        # Guarda y muestra el token de autorización
        print(f"Tu token de seguridad es: {client.client_key}")
        
        # Prueba cambiar el canal
        await client.channel_up()
        print("Comando 'Canal Arriba' enviado. Revisa la TV.")
        
    except Exception as e:
        print(f"Error al conectar: {e}")
    finally:
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(probar_lg())