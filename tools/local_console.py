from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

try:
    from tools.pm_client import PriceMonitorClient, PriceMonitorClientError
except ModuleNotFoundError:
    from pm_client import PriceMonitorClient, PriceMonitorClientError


def _print_header(client: PriceMonitorClient) -> None:
    print("")
    print("========================================")
    print("  PRICE MONITOR - CONSOLE LOCAL")
    print("========================================")
    print(f"API_BASE: {client.base_url}")
    print("")


def _print_daily_info(data: dict) -> None:
    run_times = data.get("run_times") or []
    run_times_text = ", ".join(run_times) if run_times else "-"
    latest = data.get("latest_daily_job")

    print("")
    print("Agenda diaria")
    print(f"- Ativo: {'SIM' if data.get('enabled') else 'NAO'}")
    print(f"- Horarios: {run_times_text}")
    print(f"- Proxima execucao: {data.get('next_run_at_iso')}")
    if latest:
        print(
            "- Ultimo job diario: "
            f"{latest.get('job_id')} "
            f"(status={latest.get('status')}, trigger={latest.get('trigger')})"
        )
    else:
        print("- Ultimo job diario: nenhum")


def _print_status(data: dict) -> None:
    print("")
    print("Status do job")
    print(f"- Job ID: {data.get('job_id')}")
    print(f"- Trigger: {data.get('trigger')}")
    print(f"- Status: {data.get('status')}")
    print(f"- Criado: {data.get('created_at')}")
    print(f"- Iniciado: {data.get('started_at')}")
    print(f"- Finalizado: {data.get('finished_at')}")
    print(f"- E-mail: {data.get('email_status')}")
    if data.get("email_error"):
        print(f"- Erro e-mail: {data.get('email_error')}")
    if data.get("error"):
        print(f"- Erro job: {data.get('error')}")


def _follow_job(client: PriceMonitorClient, job_id: str, interval: int = 5, max_polls: int = 240) -> dict:
    print(f"Acompanhando job {job_id}...")
    for index in range(max_polls):
        data = client.status(job_id)
        print(f"[{index + 1:03d}] status={data.get('status')}")
        if data.get("status") in {"DONE", "FAILED"}:
            return data
        time.sleep(interval)
    raise PriceMonitorClientError("Tempo limite excedido durante acompanhamento do job.")


def _run_one_shot(args: argparse.Namespace, client: PriceMonitorClient) -> int:
    if args.health:
        data = client.health()
        print(data)
        return 0

    if args.overview:
        data = client.overview()
        print(data)
        return 0

    if args.daily:
        _print_daily_info(client.daily_latest())
        return 0

    if args.run is not None:
        file_path = None if args.run.lower() == "default" else args.run
        data = client.run_job(file_path=file_path)
        print(data)
        return 0

    if args.status:
        _print_status(client.status(args.status))
        return 0

    if args.follow:
        _print_status(_follow_job(client, args.follow))
        return 0

    if args.send_email:
        data = client.send_email(args.send_email)
        print(data)
        return 0

    if args.download:
        target = client.download_output(args.download, target_path=args.output)
        print(f"Arquivo salvo em: {target.resolve()}")
        return 0

    return 1


def _interactive_menu(client: PriceMonitorClient) -> int:
    current_job_id = ""
    _print_header(client)

    while True:
        print("Escolha uma opcao:")
        print("1) Health + Overview")
        print("2) Iniciar job (arquivo .xlsx ou default)")
        print("3) Definir job atual manualmente")
        print("4) Ver status do job atual")
        print("5) Acompanhar job atual ate concluir")
        print("6) Baixar resultado do job atual")
        print("7) Enviar resultado do job atual por e-mail")
        print("8) Ver agenda diaria")
        print("9) Sair")
        choice = input("> ").strip()

        try:
            if choice == "1":
                print(client.health())
                print(client.overview())
                print("")
            elif choice == "2":
                path = input("Caminho do arquivo .xlsx (Enter para default): ").strip()
                payload = client.run_job(file_path=path or None)
                current_job_id = str(payload.get("job_id") or "")
                print(f"Job iniciado: {current_job_id}")
                print("")
            elif choice == "3":
                current_job_id = input("Digite o job_id: ").strip()
                print(f"Job atual definido: {current_job_id}")
                print("")
            elif choice == "4":
                if not current_job_id:
                    print("Nenhum job atual definido.")
                    continue
                _print_status(client.status(current_job_id))
                print("")
            elif choice == "5":
                if not current_job_id:
                    print("Nenhum job atual definido.")
                    continue
                status_data = _follow_job(client, current_job_id)
                _print_status(status_data)
                print("")
            elif choice == "6":
                if not current_job_id:
                    print("Nenhum job atual definido.")
                    continue
                target = client.download_output(current_job_id)
                print(f"Arquivo salvo em: {target.resolve()}")
                print("")
            elif choice == "7":
                if not current_job_id:
                    print("Nenhum job atual definido.")
                    continue
                print(client.send_email(current_job_id))
                print("")
            elif choice == "8":
                _print_daily_info(client.daily_latest())
                print("")
            elif choice == "9":
                print("Saindo.")
                return 0
            else:
                print("Opcao invalida.")
                print("")
        except PriceMonitorClientError as exc:
            print(f"Erro: {exc}")
            print("")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interface local em terminal para o Price Monitor.",
    )
    parser.add_argument("--api-base", default=os.getenv("API_BASE", "http://127.0.0.1:8000"))
    parser.add_argument("--api-token", default=os.getenv("API_TOKEN", ""))

    parser.add_argument("--health", action="store_true")
    parser.add_argument("--overview", action="store_true")
    parser.add_argument("--daily", action="store_true")

    parser.add_argument(
        "--run",
        metavar="FILE_OR_DEFAULT",
        help="Inicia job via API. Use 'default' para usar input.xlsx padrao.",
    )
    parser.add_argument("--status", metavar="JOB_ID")
    parser.add_argument("--follow", metavar="JOB_ID")
    parser.add_argument("--download", metavar="JOB_ID")
    parser.add_argument("--output", metavar="OUTPUT_PATH")
    parser.add_argument("--send-email", metavar="JOB_ID")
    parser.add_argument("--interactive", action="store_true", help="Forca o modo interativo.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    client = PriceMonitorClient(
        base_url=args.api_base,
        api_token=args.api_token,
    )

    try:
        result = _run_one_shot(args, client)
        if result == 0:
            return 0
        return _interactive_menu(client)
    except PriceMonitorClientError as exc:
        print(f"Erro: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
