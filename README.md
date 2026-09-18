# Servidor ESP32

Instale as dependências com `python -m pip install -r requirements.txt` e execute `python app.py` nesta pasta. O servidor escuta em todas as interfaces na porta 5050, sem depurador.

- `GET /meuip?placa=esp32c3vent&ip=192.168.2.50`: registra ou atualiza o IP da placa.
- `GET /placas`: lista os registros em JSON.
- `GET /ajustar?temperatura=25.00&umidade=61.00`: armazena uma leitura do DHT11, sem acionar equipamentos.
- `GET /temperatura`: última leitura recebida, com data e IP de origem.
- `/`: página com links para as placas.

Os dados persistem em dados.sqlite3 ao lado de app.py. Datas em UTC. A última leitura é global; o envio original não inclui identificação da placa.

Na ESP32, configure serverUrl com o IP local do computador que executa este servidor e a porta 5050. Mantenha a chamada enviarPingRaspberry() habilitada. Esse computador precisa permanecer ligado e o processo em execução. Permita a porta TCP 5050 na rede local se o firewall bloquear a comunicação. Não há autenticação; use na rede local confiável.

## Executar no Linux

Após clonar o repositório, entre na pasta que contém app.py e execute:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Abra http://localhost:5050 no computador Linux. Na ESP32, utilize http://IP_DO_LINUX:5050 como serverUrl. Para manter a aplicação ativa após fechar o terminal e reiniciar, configure um serviço systemd.

O banco de dados, ambientes virtuais e arquivos locais do Windows são excluídos do Git pelo .gitignore.
