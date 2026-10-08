# Leitor de voz

> **English summary.** A study companion for Linux (X11): hover a paragraph in Firefox and click 🔊, or select any text, and hear it read aloud with OpenAI's `gpt-4o-mini-tts`. A small desktop app (Python/Qt) keeps your API key, streams and caches the audio, and shows a mini-player. A Firefox extension adds the hover button, a selection bubble, a context-menu entry and highlights the paragraph being read. A global shortcut reads the selection in any other app. MIT licensed.

Ouça o que você está estudando. No Firefox:
- passe o mouse sobre um parágrafo e clique no **🔊**;
- ou selecione um trecho e clique em **🔊 Ler**;
- ou use o clique direito → **Ler em voz alta**.

O texto é lido com a voz do modelo `gpt-4o-mini-tts` da OpenAI, e o parágrafo em leitura fica destacado na página.

Foi feito para plataformas de questões (enunciado + alternativas), mas funciona em qualquer site. Fora do navegador, um atalho de teclado lê o texto selecionado em qualquer programa.

## Como funciona

```
Firefox ── extensão (🔊 no hover, bolha na seleção, destaque)
   │  HTTP só em 127.0.0.1
   ▼
App desktop (Python + Qt) ── OpenAI TTS (streaming PCM) ── alto-falante
   ├─ ícone na barra superior + mini-player (pausar, pular, velocidade, voz)
   └─ cache em disco: reouvir um trecho não custa nada
```

- **A chave da OpenAI fica só no app desktop.** A extensão não tem chave nenhuma e só fala com `127.0.0.1`.
- O app recusa pedidos vindos de páginas web, por checagem de `Origin`, `Host` e `Content-Type`. Assim, nenhum site consegue usar o seu saldo.
- O áudio começa a tocar em ~1–2 s, porque o primeiro pedaço é curto e chega em streaming. Os pedaços seguintes são sintetizados enquanto o anterior toca, com no máximo ~30 s de folga, para não gastar à toa se você parar.
- A velocidade (0,75×–2×) é aplicada localmente, sem mudar o tom, e pode ser trocada no meio da leitura.

## Requisitos

- Linux com **X11**. É o padrão no Ubuntu com GNOME "Ubuntu on Xorg". No Wayland, a extensão e o app funcionam, mas o atalho global de seleção não.
- Firefox 142 ou mais recente.
- [uv](https://docs.astral.sh/uv/) e Python 3.11+.
- Bibliotecas do sistema: `sudo apt install libxcb-cursor0 xclip`. O Qt 6 precisa da primeira para abrir janelas no X11.
- Uma chave da API da OpenAI com saldo.

## Instalação

```bash
git clone https://github.com/dame9177/leitor-voz.git
cd leitor-voz
uv sync
mkdir -p ~/.config/leitor-voz
echo 'OPENAI_API_KEY=sk-...' > ~/.config/leitor-voz/.env   # sua chave
chmod 600 ~/.config/leitor-voz/.env
```

Rodar o app:

```bash
uv run leitor
```

O ícone aparece na barra superior. Para abrir sozinho ao entrar na sessão e aparecer no menu de aplicativos:

```bash
./scripts/install-autostart.sh
```

Se a sua chave está em outro arquivo `.env`, use `LEITOR_ENV_FILE=/caminho/.env ./scripts/install-autostart.sh`.

**Extensão do Firefox:**
1. Baixe o `.xpi` assinado na página de [Releases](https://github.com/dame9177/leitor-voz/releases).
2. No Firefox, abra **Arquivo → Abrir arquivo…** e escolha o `.xpi`. Outra forma: arraste o arquivo para a janela.

**Atalho global (opcional):** Ctrl+Alt+L lê a seleção em qualquer programa.

```bash
./scripts/install-shortcut.sh            # ou: ./scripts/install-shortcut.sh '<Super>r'
```

## Uso

| Onde | Como |
|---|---|
| Parágrafo no Firefox | Passe o mouse e clique em 🔊. **Shift+clique** lê dali até o fim da página. |
| Trecho no Firefox | Selecione e clique em **🔊 Ler**, ou clique direito → **Ler em voz alta**. |
| Atalhos no Firefox | **Alt+Shift+R** lê a seleção ou o parágrafo sob o mouse. **Alt+Shift+P** pausa. **Alt+Shift+S** para. |
| Qualquer programa | Selecione o texto e aperte **Ctrl+Alt+L**. |
| Terminal | `leitor ler "texto"`, `leitor pausar`, `leitor parar`, `leitor proximo`, `leitor status`. |

No **mini-player**, no canto da tela, você pausa, pula para o próximo trecho, para, e escolhe velocidade e voz. Ele pode ser arrastado e some sozinho quando a leitura acaba. No **popup da extensão** dá para desligá-la num site específico ou esconder a bolha de seleção.

Configurações ficam em `~/.config/leitor-voz/config.json`:

| Campo | O que é |
|---|---|
| `voice` | Voz. `marin` e `cedar` são as recomendadas. |
| `speed` | Velocidade. |
| `model` | Modelo de voz. |
| `instructions` | Como a voz deve ler. Padrão: português do Brasil, tom didático, siglas médicas bem pronunciadas. |
| `port` | Porta local. Padrão: 47321. |
| `cache_mb` | Tamanho do cache. |

## Custos e privacidade

- O texto que você manda ler é enviado à OpenAI pelo app no seu computador. Nada mais sai da máquina.
- O custo é o da API de TTS da OpenAI, cobrado por minuto de áudio gerado. Uma questão típica custa uma fração de centavo de dólar. Trechos repetidos vêm do cache, em `~/.cache/leitor-voz`.
- **A voz é gerada por IA**, não é uma voz humana. A política de uso da OpenAI exige deixar isso claro.

## Desenvolvimento

```bash
uv sync
uv run pytest                     # testes do app (chunker, cache, áudio, servidor)
uv run leitor                     # app
./scripts/dev-firefox.sh          # Firefox separado com a extensão, recarrega ao editar
```

- `tests/extension_harness.html` é uma página que simula a API da extensão. Ela serve para testar o content script num navegador qualquer, servindo a pasta com `python3 -m http.server`.
- `tests/pagina_exemplo.html` é uma página de exemplo para testar a extensão de verdade.
- Para assinar a sua própria build da extensão, use as credenciais da [API do AMO](https://addons.mozilla.org/developers/addon/api/key/) e rode `WEB_EXT_API_KEY=… WEB_EXT_API_SECRET=… ./scripts/sign-extension.sh`. Ele baixa o `web-ext` via `npx` se não houver um local. Troque o `gecko.id` em `extension/manifest.json` se for publicar a sua versão.

### Estrutura

```
src/leitor/
  chunker.py   divide o texto em pedaços (o 1º curto, para começar rápido)
  tts.py       OpenAI TTS em streaming PCM + cache LRU em disco
  audio.py     fila de PCM por trecho + time-stretch (WSOLA) para a velocidade
  player.py    síntese em thread + reprodução com QAudioSink
  server.py    API HTTP local (/read, /control, /settings, /status)
  app.py       liga tudo: ícone, mini-player, servidor
  cli.py       comando `leitor`
extension/     extensão do Firefox (MV3)
scripts/       autostart, atalho GNOME, assinatura, Firefox de desenvolvimento
```

## Licença

[MIT](LICENSE)
