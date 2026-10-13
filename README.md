# Agente PEAS integrado à ESP32 — TCC

Backend Flask na porta **5050**. Leituras reais do DHT11 alimentam uma política reativa/cognitiva; um worker chama diretamente os endpoints da ESP32 e o feedback gostei/não gostei adapta preferências persistentes no PostgreSQL. O navegador não participa do acionamento automático.

## Executar neste notebook Windows

O ambiente `.venv` e o banco dedicado são preparados localmente. Execute na pasta `servidor-esp32`:

```powershell
& ".\.venv\Scripts\python.exe" app.py
```

Ou dê dois cliques em **iniciar.cmd**. O script não depende da política de execução do PowerShell. Abra http://localhost:5050. Na primeira utilização:

1. Ligue a ESP32 na mesma rede do notebook. Ela se registra em `/meuip` e envia `/ajustar` a cada dois minutos.
2. Deixe ventilador e umidificador fisicamente desligados e clique em **Confirmar ambos desligados**. Isso registra os estados iniciais sem enviar pulsos.
3. Escolha **Cognitivo e adaptativo** e clique em **Ativar automático**.
4. A próxima leitura inicia uma decisão no backend. Ele liga/desliga apenas quando precisa mudar o estado estimado.
5. Use **Gostei** ou **Não gostei** na última decisão executada. O feedback só altera decisões futuras.

Mesmo fechando o navegador, o worker continua enquanto o servidor estiver em execução. O notebook deve permanecer ligado. Encerrar o servidor impede novos comandos; não desliga automaticamente aparelhos já ligados.

## Ambiente e banco novos em outra máquina

Python 3.12 ou superior e PostgreSQL 17 (nativo ou Docker):

```powershell
python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
& ".\.venv\Scripts\python.exe" preparar_banco.py
& ".\.venv\Scripts\python.exe" app.py
```

`preparar_banco.py` cria **servidor_esp32**, usuário **esp32**, senha aleatória guardada apenas em `.env`, e um cluster próprio em `.postgres-data`, na porta **55432**, escutando somente em localhost. O PostgreSQL existente na porta 5432 fica separado. Ao executar `app.py`, o cluster local é iniciado se estiver parado. Ajuste `--pg-bin` caso os binários PostgreSQL estejam em outra pasta.

Alternativa Docker, com Docker instalado e ativo:

```powershell
& ".\.venv\Scripts\python.exe" preparar_banco.py --docker
& ".\.venv\Scripts\python.exe" app.py
```

Use a alternativa Docker em uma configuração nova; não mantenha simultaneamente dois bancos na porta 55432. `compose.yaml` usa `postgres:17` e volume persistente. Uma configuração nativa já criada deve continuar no modo nativo ou ser migrada com pg_dump/pg_restore. `.env.example` documenta as variáveis. Dados, credenciais e `.venv` estão excluídos do Git. O SQLite antigo não é utilizado nem apagado; este PostgreSQL é um banco novo.

## Compatibilidade com o Arduino

O firmware em `../codigoEsp32/codigoEsp32.ino` configura **192.168.2.5** na ESP32, gateway **192.168.2.254** e máscara **255.255.255.0**. O Flask anuncia o endereço atual do notebook por mDNS como `servidor-esp32.local`. A ESP encontra esse endereço, confirma `/identidade` e se registra automaticamente. Não precisa editar `serverUrl` quando o notebook mudar de IP na mesma rede.

O Flask também avisa diretamente `GET /servidor` na ESP a cada 30 segundos, sem gerar pulsos. A placa obtém o IP de origem desse aviso e confirma `/identidade` antes de se registrar. Essa alternativa funciona quando multicast mDNS está bloqueado. `ESP_FIXED_IP` seleciona a placa de destino e usa `.5` por padrão; o IP variável do notebook continua sendo descoberto automaticamente.

Esta atualização exige enviar o novo firmware uma vez pelo Arduino IDE e reiniciar o Flask com as novas dependências. Veja [REDE_ESTAVEL.md](REDE_ESTAVEL.md) para instalação e testes. A configuração estática da ESP não reserva o endereço no roteador: somente a Netline pode garantir que o DHCP não entregue `.5` a outro equipamento.

Cada GET na ESP32 `/ventilador` ou `/umidificador` executa um pulso de 200 ms. O backend realiza **três chamadas sequenciais para ligar** e **uma para desligar**, com intervalo de 350 ms entre os pulsos de ligar, conforme o protocolo informado para esta montagem. A inicialização sem pulso e a interpretação corrigida da boia foram preservadas.

O DHT11 envia `GET /ajustar?temperatura=...&umidade=...`. A leitura é identificada pelo IP real de origem registrado em `/meuip`. A ingestão responde sem acionar hardware. A fila aguarda pelo menos um segundo e consulta `/nivel` antes da execução, pois o HTTPClient síncrono do firmware impede a ESP32 de atender comandos enquanto espera a resposta do Flask.

## API

Todos os endereços abaixo são do Flask, na porta 5050. Quando existir mais de uma placa, acrescente `?placa=esp32c3vent`.

| Método | Rota | Função |
|---|---|---|
| GET | `/agente` | Painel do agente (também disponível em `/`) |
| GET | `/identidade` | Identificação do projeto para descoberta da ESP |
| GET | `/rede/status` | Estado do anúncio mDNS e IP atual do notebook |
| GET | `/meuip?placa=NOME&ip=IP&ip_fixo=1` | Registro periódico e indicação de IP estático da ESP32 |
| GET | `/ajustar?temperatura=T&umidade=U` | Recebe leitura e enfileira processamento |
| GET | `/placas` | Lista placas registradas |
| GET | `/esp/conexao` | Consulta a boia sem pulsar relés |
| GET | `/temperatura` | Última leitura real e data |
| POST | `/ventilador/ligar` | 3 pulsos se estiver estimado desligado |
| POST | `/ventilador/desligar` | 1 pulso se estiver estimado ligado |
| POST | `/umidificador/ligar` | 3 pulsos se estiver estimado desligado e tiver água |
| POST | `/umidificador/desligar` | 1 pulso se estiver estimado ligado |
| POST | `/agente/sincronizar` | Informa estado físico inicial observado |
| POST | `/agente/configurar` | Ativa/pausa automático e seleciona modo |
| POST | `/agente/decidir` | Prévia sem executar comandos |
| POST | `/agente/feedback` | Gostei/não gostei associado à decisão |
| GET | `/agente/status` | Estados estimados, decisão e preferências |
| GET | `/historico` | Últimas 50 decisões e resultados |
| GET | `/analise` | Contagens, falhas e médias das leituras |

Rotas legadas `/interf/ligarventilador`, `/interf/desligarventilador`, `/interf/ligarumidificador`, `/interf/desligarumidificador` apontam para os mesmos métodos. `POST /ventilador` e `POST /umidificador` agora significam **ligar com três pulsos**, e não apenas um clique. `/interf/feedback` aceita o contrato booleano abaixo.

```powershell
$base = "http://localhost:5050"
Invoke-RestMethod "$base/placas"
Invoke-RestMethod -Method Post "$base/agente/sincronizar" -ContentType "application/json" -Body '{"ventilador":false,"umidificador":false}'
Invoke-RestMethod -Method Post "$base/agente/configurar" -ContentType "application/json" -Body '{"automatico":true,"modo":"cognitivo"}'
Invoke-RestMethod "$base/agente/status" | ConvertTo-Json -Depth 12
Invoke-RestMethod -Method Post "$base/agente/feedback" -ContentType "application/json" -Body '{"decisao_id":"ID_DA_DECISAO","gostei":false}'
```

## Como a integração atende a arquitetura PEAS

`agente_peas/services.py` e `config.py` vieram do projeto local `atividade-peas-v1`, junto com o protocolo Python compartilhado. A versão original altera estados em `apply_device_command`/`execute_plan` e avança uma física simulada em `run_cycle`. Nesta montagem, `Controller._command` assume a execução real, persiste a intenção e chama `EspTransport.set_state`. `agente_hardware.decidir` adapta as alternativas aos dois atuadores existentes, reutilizando funções públicas PEAS de conforto, custo, economia, ajuste de preferência e utilidade. Não são copiados templates ou a cena 3D do amigo.

O perfil reativo liga o ventilador acima de **25 °C** e desliga em **23 °C** ou menos; liga o umidificador abaixo de **40%** e desliga em **50%** ou mais. Nas faixas intermediárias mantém o estado para evitar alternância. Falta de água bloqueia ligar o umidificador; calor de **32 °C** ou mais e umidade de **80%** ou mais têm prioridade reativa sobre preferências.

O perfil cognitivo compara ligar/desligar por dispositivo: **0,6 × adequação + 0,4 × economia + preferência/10**. A adequação é uma heurística explícita alinhada à regra reativa, baseada nas leituras atuais; não representa previsão de queda da temperatura. O ventilador não é tratado como ar-condicionado. As alternativas, notas e justificativas ficam registradas para análise.

O perfil adaptativo recebe feedback booleano da decisão executada e soma **+1** (gostei) ou **−1** (não gostei), com limites **−3/+3**, para cada alternativa escolhida que não era prioridade reativa. A chave inclui dispositivo, ação, faixa de temperatura, faixa de umidade e horário. Em situações semelhantes, a preferência muda a utilidade e pode mudar a escolha. Reenviar o mesmo feedback não aprende duas vezes; feedback conflitante para a mesma decisão retorna 409. É aprendizagem incremental por reforço de preferência, sem rede neural nem treinamento externo.

## Estados e recuperação

A confirmação `OK` mede a execução do pulso no firmware, e não o estado físico do aparelho. O banco armazena um **estado estimado**, fundamentado na sincronização inicial e na sequência de cliques informada. Não envia novamente ligar/desligar se já estima o mesmo estado. Pulsos são serializados por placa, inclusive entre processos via advisory lock PostgreSQL.

Antes do primeiro pulso, a intenção é gravada e o estado passa a desconhecido. Falha ou interrupção deixa esse estado desconhecido; não há repetição automática de pulsos. Sincronize fisicamente de novo para retomar. Se apertar botões do aparelho, usar a página direta da ESP32 ou reiniciar a placa, pause e sincronize. O firmware atual não fornece estado/boot_id e não detecta sozinho essas alterações. Troca de IP ou retorno após mais de cinco minutos sem atividade invalida estados e pausa o automático.

Leituras com mais de cinco minutos não acionam comandos. Leituras antigas substituídas por uma mais nova não executam. Histórico inclui leituras, boia, decisões, alternativas, resultados por aparelho, comandos, pulsos confirmados/tentados, falhas e feedbacks. Preferências sobrevivem ao reinício do servidor. `/analise` faz agregações sobre dados reais; não infere sozinho eficácia física dos aparelhos.

## Verificação

```powershell
& ".\.venv\Scripts\python.exe" -m unittest discover -v
& ".\.venv\Scripts\python.exe" testar_postgres.py
```

A suíte substitui o transporte HTTP por uma fixture e não aciona aparelhos. A suíte PostgreSQL cria schemas temporários `tcc_test_*`, testa o backend e remove apenas esses schemas. Não apaga registros do banco real. Casos cobrem 3/1 pulsos, timeout parcial, ausência de repetição, fila independente da interface, histerese, feedback, adaptação após rejeições, persistência, origem das leituras, concorrência e prioridade da boia.

Referências técnicas: [SQLAlchemy PostgreSQL](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#psycopg), [Psycopg](https://www.psycopg.org/psycopg3/docs/basic/install.html), [projeto PEAS de origem](https://github.com/vonderheidon/atividade-peas-v1).
