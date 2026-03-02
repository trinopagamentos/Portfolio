![Trino Pagamentos](https://trinopagamentos.com/assets/img/logo-trino-verde.svg)

# Portfólio

## Contexto do projeto
Este projeto foi criado para exibir o inventário de equipamentos da Trino, servindo como apoio para organização logística, planejamento de implantação e preparação de festas/eventos.

## Objetivo
Centralizar a visualização dos equipamentos disponíveis de forma simples e prática, facilitando consultas rápidas e decisões operacionais no dia a dia.

## Uso esperado
- Consultar os equipamentos cadastrados no inventário.
- Apoiar o time na separação de itens para implantações.
- Auxiliar no planejamento de materiais para festas e ações internas.

## Deploy via CLI (GitHub Actions)

Dispare o deploy de produção direto pelo terminal (ou pelo Cursor) usando o [GitHub CLI](https://cli.github.com/):

```bash
# Disparar deploy em produção
gh workflow run production.deploy.yml --ref main

# Acompanhar execução em tempo real
gh run watch

# Listar últimas execuções
gh run list --workflow=production.deploy.yml

# Ver logs de uma execução específica
gh run view <run-id> --log
```

> **Pré-requisitos:** `gh` instalado (`brew install gh`) e autenticado (`gh auth login`).

### Deploy pelo painel do GitHub

Também é possível disparar o deploy diretamente pelo navegador:

1. Acesse [Actions → Deploy to Production](https://github.com/trinopagamentos/Portfolio/actions/workflows/production.deploy.yml)
2. Clique em **Run workflow**
3. Selecione a branch `main` e confirme
