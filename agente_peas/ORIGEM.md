# Origem do backend

services.py e config.py vieram de https://github.com/vonderheidon/atividade-peas-v1
Commit: 5521fb7300f31805a9de92b48abe0287b093bbe2
Autor do projeto de origem: vonderheidon e colaboradores.

Adaptação: import relativo de config. Não foram copiados templates, assets ou frontend 3D.
A integração chama make_decision em uma cópia isolada do estado. Não executa a física simulada, não confirma estados reais e não ativa aprendizagem ou feedback.
