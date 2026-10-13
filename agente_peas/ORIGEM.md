# Origem do backend

Código Python atualizado a partir da pasta local `atividade-peas-v1`, em 08/10/2026, projeto https://github.com/vonderheidon/atividade-peas-v1 (vonderheidon e colaboradores).

Copiados `services.py`, `config.py` e o pacote `shared`. Alterados somente os imports para relativos ao pacote `agente_peas`. Não foram copiados templates, JavaScript, cena 3D ou assets.

O perfil de hardware em `agente_hardware.py` reutiliza funções públicas de custo, economia, conforto e utilidade; o controlador real substitui a simulação da atuação/física por HTTP e novas leituras DHT11. `Controller._command` é o ponto central para a execução real. Feedback é persistido e correlacionado por decisão. As funções simuladas permanecem disponíveis no código de referência, mas `run_cycle` não é usado no hardware.
