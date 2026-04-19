# RPA Gemini

Automação de interação com o [Gemini](https://gemini.google.com) via Playwright. O projeto expõe três módulos independentes — chat, extração de PDF e geração de código — todos acessíveis por uma CLI unificada ou importáveis como biblioteca Python.

---

## Sumário

- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Frontend local](#frontend-local)
- [Primeiro uso — Login](#primeiro-uso--login)
- [Arquitetura](#arquitetura)
- [Módulos](#módulos)
  - [chat — Mensagem simples](#chat--mensagem-simples)
  - [pdf — Extração de Boletos e Documentos](#pdf--extração-de-boletos-e-documentos)
  - [code — Geração de código Python](#code--geração-de-código-python)
- [CLI unificada — main.py](#cli-unificada--mainpy)
- [Uso como biblioteca](#uso-como-biblioteca)
- [Substituição de variáveis](#substituição-de-variáveis)

---

## Requisitos

- Python 3.10+
- Conta Google com acesso ao Gemini

Se o seu sistema ainda usa uma versão mais antiga (por exemplo, Python 3.6), instale uma versão moderna ou use `python3.12`/`python3.11` para executar o projeto.

## Instalação

```bash
pip install -r requirements.txt

# Instala o navegador Chromium usado pelo Playwright
python3 -m playwright install chromium
```

---

## Frontend local

O projeto agora inclui um frontend local em Flask com dois módulos independentes:

- `webapp/chat_module.py` → chat Gemini via texto.
- `webapp/pdf_module.py` → análise de PDFs e retorno em JSON.

Para executar a interface local (use `python3` se `python` ainda aponta para Python 2):

```bash
python3 run_webapp.py
```

Abra `http://127.0.0.1:5000` no navegador.

---

## Primeiro uso — Login

O projeto utiliza um perfil persistente do Chromium salvo em `~/.gemini_rpa_profile`. Na **primeira execução** é necessário fazer login na conta Google:

```bash
python3 main.py chat -m "olá" --show-browser
```

O navegador abrirá visível. Faça login no Google normalmente. Nas execuções seguintes o login fica salvo e o navegador pode rodar em modo headless (invisível).

---

## Arquitetura

```
gemini_shared.py          ← primitivas Playwright compartilhadas
    ├── gemini_chat.py    ← módulo: chat simples (texto → texto)
    ├── gemini.py         ← módulo: extração de PDF (PDF + prompt → JSON)
    ├── gemini_code_python.py  ← módulo: gerador de código (HTML + JSON + prompt → Python)
webapp/                   ← frontend Flask local
    ├── app.py            ← inicializa o app Flask e registra módulos
    ├── chat_module.py    ← rota de chat do Gemini
    ├── pdf_module.py     ← rota de análise de PDF
    ├── templates/        ← páginas e layout do frontend
    └── static/           ← CSS do frontend moderno

main.py                   ← CLI unificada com subcomandos: chat | pdf | code
run_webapp.py             ← executa a interface web local
```

**`gemini_shared.py`** contém todas as primitivas reutilizadas: abertura do browser, injeção de texto via clipboard, polling de resposta, envio multi-turno para documentos grandes, chunking de texto e substituição de variáveis.

---

## Módulos

### chat — Mensagem simples

Envia uma mensagem de texto ao Gemini e retorna a resposta como string.

```bash
python3 main.py chat --message "Explique o que é RPA em 2 frases"
python3 main.py chat -m "Explique o que é RPA em 2 frases"

# Mensagem de arquivo
python3 main.py chat --message-file pergunta.txt

# Salvar resposta
python3 main.py chat -m "O que é machine learning?" --output resposta.txt
```

---

### pdf — Extração de Boletos e Documentos

Lê um arquivo PDF (como um boleto bancário ou nota fiscal), envia o conteúdo ao Gemini junto com um prompt de análise e retorna os dados extraídos como **JSON estruturado**.

Para documentos grandes (acima de ~28 mil caracteres), o conteúdo é enviado automaticamente em múltiplos turnos de conversa antes de solicitar a resposta.

```bash
# Extração de boleto usando o arquivo de prompt
python3 main.py pdf \
    --pdf boleto_ficticio.pdf \
    --prompt-file prompt.txt \
    --output resultado.json
```

**Exemplo de Prompt (`prompt.txt`):**
```text
Extraia: cedente, cpf_cnpj_cedente, sacado, vencimento, valor_documento, linha_digitavel.
Retorne apenas o JSON.
```

**Saída de exemplo:**

```json
{
  "cedente": "Binho Informática S/C Ltda",
  "cpf_cnpj_cedente": "803.986.914-52",
  "sacado": null,
  "vencimento": "17/04/2026",
  "data_documento": "17/04/2026",
  "valor_documento": 260.35,
  "linha_digitavel": "34195.17515 23456.787128 34123.456005 2 10419000002603",
  "nosso_numero": "175/12345678-7",
  "agencia_codigo_cedente": "1234 / 123456-0"
}
```

**Estratégias de envio (em cascata):**

| Estratégia | Quando | Como |
|---|---|---|
| Upload nativo | Botão de upload disponível no Gemini | Envia o arquivo PDF diretamente |
| Multi-turno | Fallback (padrão atual) | Texto extraído em partes de ~28k chars + disparo final |

---

### code — Geração de código Python

Recebe o HTML de uma página, dados em JSON e instruções em texto. O Gemini analisa a estrutura dos elementos e retorna um **script Python Playwright executável** que realiza o preenchimento e as ações solicitadas.

O código gerado expõe uma função `run(page)` que recebe um objeto `page` do Playwright **já navegado** para a página correta. A aplicação chamadora é responsável por abrir o navegador e navegar — o código gerado apenas interage com os elementos.

```bash
# Gerar código e imprimir no stdout
python3 main.py code \
    --html-file formulario.html \
    --json-file dados.json \
    --prompt "Preencha todos os campos e clique em Enviar"

# Salvar em arquivo
python3 main.py code \
    --html-file formulario.html \
    --json-file dados.json \
    --prompt "Preencha todos os campos e clique em Enviar" \
    --output script_gerado.py

# Salvar e executar imediatamente
python3 main.py code \
    --html-file formulario.html \
    --json-file dados.json \
    --prompt "Preencha todos os campos e clique em Enviar" \
    --output script_gerado.py \
    --execute
```

**Estrutura do código gerado:**

```python
import time
from playwright.sync_api import Page, sync_playwright

def run(page: Page) -> None:
    data = { "campo": "valor", ... }

    page.wait_for_selector("#formulario")
    page.fill("#nome", data["nome"])
    page.select_option("#estado", data["estado"])
    page.check("#aceitar_termos")
    page.click("#btn-enviar")

if __name__ == "__main__":
    # Bloco de teste local — a aplicação principal NÃO usa este bloco
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto("about:blank")  # substitua pela URL de teste
        run(page)
        input("Pressione Enter para fechar...")
        browser.close()
```

**Como a aplicação chamadora usa o código gerado:**

```python
from playwright.sync_api import sync_playwright
from gemini_code_python import generate_code

# 1. Obtém o HTML da página aberta
html = page.content()

# 2. Gera o código de automação
codigo = generate_code(
    html_content=html,
    json_data={"nome": "João Silva", "estado": "MG"},
    user_prompt="Preencha o formulário e clique em Enviar",
)

# 3. Executa o código na página já aberta
exec(codigo)
run(page)
```

---

## CLI unificada — main.py

```
python3 main.py <subcomando> [opções]

Subcomandos:
  chat   Mensagem simples → resposta em texto
  pdf    PDF + prompt     → JSON estruturado
  code   HTML + JSON + prompt → script Python Playwright
```

### Opções comuns a todos os subcomandos

| Opção | Descrição |
|---|---|
| `--var CHAVE=VALOR` | Substitui `{chave}` no prompt/mensagem. Repetível. |
| `--output ARQUIVO` | Salva a saída em arquivo (padrão: stdout). |
| `--show-browser` | Exibe o navegador Chromium durante a execução. |

### Referência completa

```bash
# chat
python3 main.py chat --help

# pdf
python3 main.py pdf --help

# code
python3 main.py code --help
```

---

## Uso como biblioteca

Todos os módulos podem ser importados diretamente em outros projetos Python:

```python
# Chat simples
from gemini_chat import chat

resposta = chat("Qual a capital do Brasil?")
print(resposta)

# Extração de PDF
from gemini import extract_from_pdf

dados = extract_from_pdf(
    pdf_path="contrato.pdf",
    user_prompt="Extraia as partes, o objeto e o valor do contrato",
)
print(dados["objeto"])

# Geração de código
from gemini_code_python import generate_code

codigo = generate_code(
    html_content=html,
    json_data={"nome": "Maria", "cpf": "000.000.000-00"},
    user_prompt="Preencha o cadastro com os dados fornecidos",
    output_file="automacao.py",
)
```

---

## Substituição de variáveis

Qualquer `{chave}` no prompt ou mensagem é substituída pelo valor passado via `--var`:

```bash
python3 main.py pdf \
    --pdf boleto_ficticio.pdf \
    --prompt-file prompt.txt \
    --var analista=João
```

No arquivo `prompt.txt`:

```
Compare a data de vencimento com {data_atual} e informe se o boleto
tem menos de 30 dias. Analista responsável: {analista}.
```

Múltiplas variáveis são suportadas repetindo `--var`.
