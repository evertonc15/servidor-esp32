# IP estático da ESP e descoberta do Flask

A ESP usa `192.168.2.5`, gateway `192.168.2.254` e máscara `255.255.255.0`. O notebook continua usando DHCP. O Flask anuncia o IP atual por mDNS como `servidor-esp32.local`, na porta HTTP 5050, e acompanha mudanças da interface a cada 10 segundos. Sem endereço conhecido, a ESP procura o anúncio a cada 15 segundos. Antes de enviar dados, confirma que `/identidade` responde `ESP32_TCC_V1`.

Como alternativa independente de multicast, o Flask também chama `GET http://192.168.2.5/servidor` a cada 30 segundos, ou na próxima verificação de rede quando o IP local mudar. Esse endpoint não gera pulsos. A ESP identifica o IP real do remetente, responde `DESCOBERTA_ACEITA` e só depois confirma `/identidade`, no loop principal. Assim, os dois clientes HTTP não ficam esperando um pelo outro. Em seguida, a ESP envia `/meuip` e suas leituras normalmente.

## Aplicar a atualização

1. Pause o automático no painel atual. Deixe ventilador e umidificador fisicamente desligados.
2. Encerre o Flask antigo com Ctrl+C. Na pasta `servidor-esp32`, instale as dependências caso ainda não tenham sido instaladas:

   ```powershell
   & ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
   ```

3. Abra `../codigoEsp32/codigoEsp32.ino` no Arduino IDE, selecione ESP32 Dev Module e a porta conectada, clique em Verificar e depois Enviar. O Wi-Fi existente foi preservado. Não é necessário instalar uma biblioteca externa para ESPmDNS: ela acompanha o pacote ESP32. DHT e suas dependências continuam necessárias.
4. Inicie o Flask por `iniciar.cmd` ou pelo comando abaixo e mantenha notebook e ESP na mesma rede de casa:

   ```powershell
   & ".\.venv\Scripts\python.exe" app.py
   ```

O banco recebe a coluna `static_ip` na próxima inicialização, preservando os registros existentes. O firmware informa `ip_fixo=1` no registro. Esse campo descreve a configuração da placa; não é uma reserva DHCP nem uma verificação de exclusividade no roteador.

## Conferir sem acionar relés

Abra [estado da rede](http://localhost:5050/rede/status). Espere `ativo: true`, `porta: 5050` e `enderecos` com o IP atual do notebook. Em [placas](http://localhost:5050/placas), após o registro, a ESP deve aparecer com `ip: 192.168.2.5` e `ip_fixo: true`.

No Monitor Serial a 115200 baud, espere (a descoberta pode ser por mDNS ou aviso HTTP):

```text
Wi-Fi conectado! IP estatico da ESP: http://192.168.2.5
Servidor Flask encontrado automaticamente: http://<IP-atual-do-notebook>:5050
Envio confirmado: HTTP 200
```

Com o aviso direto, a mensagem é `Servidor Flask encontrado por aviso HTTP: http://<IP-atual-do-notebook>:5050`. Em `/rede/status`, `aviso_http.aceito: true` indica que a ESP recebeu o aviso; confira também `/placas` para confirmar o registro. Um erro HTTP 404 no aviso normalmente significa que a placa ainda está com o firmware anterior.

Também pode consultar [temperatura da ESP](http://192.168.2.5/temperatura) e [nível da ESP](http://192.168.2.5/nivel). A API de nível normaliza a leitura: `1` significa com água e `0` significa sem água. A ligação física permanece LOW = com água.

No [painel](http://localhost:5050/agente), confirme ambos desligados e só então ative o automático. Uma leitura chega a cada dois minutos. Após usar botões físicos, comandos diretos na ESP ou reiniciar a placa, pause e sincronize novamente os estados observados.

## Quando o notebook mudar de endereço

O anúncio será atualizado; a ESP abandona o endereço antigo quando a identificação ou o envio falhar e volta a procurar o servidor. Aguarde alguns ciclos de descoberta e registro, pois caches mDNS podem atrasar a troca. Não precisa regravar o Arduino só porque o notebook mudou de IP dentro de `192.168.2.0/24`.

Se `/rede/status` indicar que não há IPv4 na rede configurada, confira a conexão Wi-Fi do notebook. `DISCOVERY_NETWORK` no `.env` permite selecionar a rede anunciada; para mudar a rede da ESP também é preciso ajustar IP, gateway, máscara e Wi-Fi no firmware.

Se o anúncio estiver ativo, mas a ESP não descobrir o Flask, confira `aviso_http` em `/rede/status`. O aviso direto precisa apenas de HTTP entre notebook e ESP; não depende de UDP 5353. Se a ESP receber o aviso, mas `/identidade` falhar, teste `http://<IP-do-notebook>:5050/identidade` em outro dispositivo no mesmo Wi-Fi. O Firewall do Windows deve permitir HTTP TCP 5050 na rede local. Não desative o firewall inteiro. Isolamento entre clientes pode bloquear inclusive HTTP; bloqueio só de multicast não impede a alternativa direta.

`ESP_FIXED_IP` no `.env` define o destino do aviso (padrão `192.168.2.5`). Se mudar esse endereço, ajuste também o IP estático no Arduino. O IP variável do notebook não precisa ser cadastrado no `.env` nem no firmware.

## Limite do IP estático sem acesso ao roteador

A ESP configura seu próprio endereço e não pede uma reserva ao roteador. Sem conhecer ou alterar a faixa DHCP, não há garantia de que outro dispositivo não receba `192.168.2.5`. Para garantir exclusividade, peça à Netline uma reserva para a ESP ou exclusão desse endereço da faixa DHCP. A senha administrativa não é necessária para configurar o firmware, mas essa garantia depende do provedor.

## Verificações desta atualização

A suíte usa transporte simulado e não pulsa os relés. Os testes PostgreSQL usam schemas temporários. Um teste separado confirmou anúncio/resolução mDNS e `/identidade` por HTTP no notebook, com worker desativado. Isso não substitui o teste após enviar o firmware à placa real.

Referências: [Wi-Fi da Espressif](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/wifi.html), [API python-zeroconf](https://python-zeroconf.readthedocs.io/en/latest/api.html).
