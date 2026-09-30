' Despertador do robô: pede ao GitHub para rodar o "ciclo" (ler o Telegram e publicar o que está na hora).
' Chamado a cada 20 minutos pela tarefa agendada do Windows "LuzSemSusto_Despertador" (sem abrir janela).
' O agendador gratuito do GitHub atrasa muito; este despertador garante a pontualidade enquanto o PC estiver ligado.
CreateObject("WScript.Shell").Run """C:\Program Files\GitHub CLI\gh.exe"" workflow run ciclo.yml --repo ricardoromanini/robo-luz-sem-susto", 0, False
