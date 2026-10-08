# Contribuindo

Contribuições são bem-vindas: issues com bugs, ideias ou pull requests.

- Rode `uv run pytest` antes de abrir o PR.
- Na extensão, rode `npx web-ext lint --source-dir extension` e teste com `./scripts/dev-firefox.sh`.
- Mantenha a regra de segurança: **a chave da API nunca vai para a extensão**, e o servidor local só aceita pedidos da extensão ou de clientes locais sem `Origin`.
- Textos da interface em português do Brasil. Código e comentários podem ficar em inglês.
- Se o bug for num site específico, que mostra o 🔊 no lugar errado ou lê o trecho errado, descreva a estrutura do HTML. Só o trecho relevante, sem dados pessoais.
