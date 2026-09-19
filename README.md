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

## Backend do agente e comandos da ESP32

Requer Python 3.11 ou superior. Backend de decisão adaptado de [atividade-peas-v1](https://github.com/vonderheidon/atividade-peas-v1), sem interface 3D. A origem e o commit estão em agente_peas/ORIGEM.md.

- `POST /ventilador` ou `POST /interf/ligarventilador`: envia um GET para `/ventilador` da ESP32.
- `POST /umidificador` ou `POST /interf/ligarumidificador`: envia um GET para `/umidificador` da ESP32.
- `GET /esp/conexao`: testa a conexão consultando `/nivel`, sem pulsar relés.
- `POST /agente/decidir` com JSON `{"modo":"reativo"}` ou `{"modo":"cognitivo"}`: usa a leitura recente da placa (até 5 minutos) e retorna o plano do agente, sem executá-lo.

Seleção de placa: acrescente `?placa=esp32c3vent`. Sem esse parâmetro, é necessário existir exatamente uma placa registrada via `/meuip`.

```bash
curl http://localhost:5050/esp/conexao
curl -X POST http://localhost:5050/ventilador
curl -X POST http://localhost:5050/umidificador
curl -X POST http://localhost:5050/agente/decidir -H 'Content-Type: application/json' -d '{"modo":"reativo"}'
```

Cada comando gera UM clique. Ambos os aparelhos têm um ciclo de três cliques, mas a sequência exata dos modos ainda precisa ser informada. Os nomes legados `ligar...` não garantem estado ligado. O backend não repete requisições, não presume estado físico e não executa automaticamente os planos binários do simulador. Um timeout pode ocorrer após o clique já ter sido executado.

O plano original também pode incluir janela, ar-condicionado e lâmpada, que não existem nesta montagem. Sensores adicionais e estados usam o preset conforto e aparecem explicitamente como contexto presumido na resposta. Feedback e aprendizagem não estão ativados. Para execução automática real, é necessário mapear os três modos de cada aparelho e sincronizar o estado inicial, ou alterar o firmware para expor comandos e leitura de estado.

A ESP32 atual usa HTTP síncrono para enviar `/ajustar`. Por isso essa rota apenas armazena a leitura: chamar a ESP32 de volta dentro da mesma requisição impediria o firmware de atender o comando a tempo.

Testes: `python -m unittest -v test_backend.py` (transporte HTTP simulado, sem acionar equipamentos).
