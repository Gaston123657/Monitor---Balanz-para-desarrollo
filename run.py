import os
import sys
import logging

from config.settings import setup_logging

from apps.cli.monitors.bonares import generate_bonares_report
from apps.cli.monitors.bopreales import generate_bopreales_report
from apps.cli.monitors.comparacion_tirs import generate_comparacion_report
from apps.cli.monitors.cer import generate_cer_report
from apps.cli.monitors.tasa_fija import generate_tasa_fija_report
from apps.web.server import main as web_server_main

setup_logging()
logger = logging.getLogger(__name__)

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, "data")
    
    monitors = [
        {"name": "BONARES Y GLOBALES", "func": generate_bonares_report},
        {"name": "BOPREALES", "func": generate_bopreales_report},
        {"name": "TASA FIJA (LECAPS / BONCAPS)", "func": generate_tasa_fija_report},
        {"name": "BONOS CER", "func": generate_cer_report},
        {"name": "COMPARACION DE TIR'S", "func": generate_comparacion_report},
        {"name": "INICIAR MONITOR WEB (Dashboard Interactivo)", "func": lambda _: web_server_main()}
    ]

    print("="*60)
    print("      GENERADOR DE IMÁGENES - MONITORES DE BONOS")
    print("="*60)
    
    print("\nSelecciona el monitor que deseas generar:\n")
    for i, monitor in enumerate(monitors, 1):
        print(f"  [{i}] {monitor['name']}")
    print(f"  [0] Salir")
    print("\n" + "="*60)

    while True:
        try:
            choice = input("\nIngresa el número de tu opción: ").strip()
            if choice == "0":
                print("Saliendo...")
                break
            
            idx = int(choice) - 1
            if 0 <= idx < len(monitors):
                selected = monitors[idx]
                
                print(f"\n=> Ejecutando generador para: {selected['name']}...")
                print("-" * 60)
                
                # Ejecutar
                if "WEB" in selected["name"]:
                    print("\nAbriendo el servidor web en http://localhost:8000 ...")
                    selected["func"](None)
                else:
                    png_path = selected["func"](output_dir)
                    
                    if png_path and os.path.exists(png_path):
                        print(f"\n[OK] Imagen generada con éxito en:")
                        print(f"-> {png_path}")
                        try:
                            # En Windows os.startfile abre la imagen con el visor predeterminado
                            os.startfile(png_path)
                        except Exception:
                            pass
                    else:
                        print("\n[ERROR] No se pudo generar la imagen.")
                    
                print("-" * 60)
                break
            else:
                print("Opción inválida. Intenta nuevamente.")
        except ValueError:
            print("Por favor, ingresa un número válido.")

    print("Generación finalizada. Presiona Enter para salir.")
    input()

if __name__ == "__main__":
    main()
