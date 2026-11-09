# Análise de consumo de energia

Aplicação web local em Python para registrar leituras de energia da rede geral e de circuitos individuais. O banco SQLite fica em `data/energia.db`.

## Executar no Windows

Instale Python 3.10 ou superior e, no terminal dentro desta pasta, execute:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Abra [http://127.0.0.1:5000](http://127.0.0.1:5000). Para interromper o servidor, pressione `Ctrl+C` no terminal.

## Como funciona

- Cadastre os circuitos que deseja acompanhar e registre leituras da rede geral ou de um circuito.
- Cada leitura contém o consumo em kWh e o intervalo de início e fim ao qual esse consumo corresponde.
- O painel filtra por circuito e por últimos 7 dias, últimos 30 dias, mês atual ou intervalo personalizado.
- Consumo e custo são apresentados para manhã, tarde e noite, além de médias diárias e projeções semanais e mensais.
- A tarifa inicial é R$ 0,95/kWh e pode ser alterada em Ajustes. Substitua pelo valor efetivo da sua conta de energia.
- O perfil inicial distribui 20% do consumo pela manhã, 30% à tarde e 50% à noite; os percentuais podem ser ajustados e devem somar 100%.

As faixas horárias são uma estimativa ponderada aplicada ao intervalo informado, não uma medição horária. As projeções semanais e mensais extrapolam a média diária do período filtrado; a projeção mensal considera 30 dias. Leituras da rede geral e de circuitos são exibidas separadamente para evitar somá-las como se fossem consumos independentes.
