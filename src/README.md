# Syntax Executor v1

Roblox Luau bytecode executor via pointer-swapping. Injects compiled Luau into a running Roblox process and communicates through a local HTTP bridge.

> **AVISO:** Projeto criado exclusivamente para fins educativos e uso em servidores privados. Não utilize em servidores públicos.

---

## Arquitetura

```
┌──────────────────────┐      ┌────────────────────┐
│  app.py (Host)       │      │  RobloxPlayerBeta   │
│                      │      │                     │
│  • pymem attach      │─────▶│  • LocalScript      │
│  • DataModel walk    │      │    ↓                │
│  • Bytecode compile  │ mem  │  • ByteCode Struct  │
│  • Pointer swap      │─────▶│    ├─ ptr  (swapped)│
│                      │      │    └─ size (updated)│
│  • Flask bridge ─────│─HTTP─│  • Luau VM exec     │
│    (localhost:19283)  │◀────│    │                 │
└──────────────────────┘      └────────────────────┘
```

### Pipeline

1. **Attach** — pymem hooks into `RobloxPlayerBeta.exe`, resolves base address.
2. **Compile** — `rbxinit.py` generates a Luau payload; the compiler (Python fallback or native DLL) produces signed Roblox bytecode.
3. **Locate** — Walks the DataModel children tree via offsets to find the target `LocalScript` by name.
4. **Inject** — Allocates remote memory, writes the new bytecode, then swaps the `bytecode->pointer` and `bytecode->size` fields on the target's `ByteCode` struct.
5. **Bridge** — The injected Luau runtime polls `GET /send?c=gs` for scripts pushed by the user at `POST /execute`.

---

## Estrutura do Projeto

| Arquivo | Descrição |
|---------|-----------|
| `app.py` | Entry point. Process attach, DataModel walk, bytecode injection loop. |
| `rbxinit.py` | Luau payload generator – compiled and injected as the init script. |
| `rbxbcd.py` | Flask HTTP bridge. UNC file I/O and script execution queue. |
| `Encoder.py` | Thin wrapper over the Luau compile / sign / pack pipeline. |
| `Updater.py` | Fetches the latest offsets from a remote endpoint. |
| `NewestOffsets.txt` | Static offset database (393 entries). Used at startup. |
| `app.spec` | PyInstaller spec for building a standalone `.exe`. |
| `third_party/luau/` | Python port of the Luau compiler (lexer, bytecode builder, signing). |
| `workspace/` | UNC sandbox – read/write operations are confined here. |

---

## Dependências

```
pip install pymem flask blake3 zstandard requests
```

| Biblioteca | Uso |
|------------|-----|
| `pymem` | Leitura/escrita de memória no processo Roblox |
| `flask` | Servidor HTTP local (ponte UNC + fila de scripts) |
| `blake3` | Hashing usado na assinatura de bytecode Roblox |
| `zstandard` | Compressão ZSTD para o header RBYT |
| `requests` | Atualizador de offsets (Updater.py) |

---

## Uso

### Iniciar

```powershell
python app.py
```

O executor aguarda `RobloxPlayerBeta.exe` ser aberto e injeta automaticamente.

### Executar scripts no Roblox

```powershell
curl -X POST http://localhost:19283/execute --data "print('Hello from Syntax v1')"
```

O script é enfileirado. O Luau injectado faz polling (`/send?c=gs`) e executa via `loadstring()`.

### Compilar offline (teste)

```python
from Encoder import encode_script, quick_test

bytecode = encode_script("print('hello')", pack=True)
print(f"Compiled {len(bytecode)} bytes")

if quick_test("local x = 1 + 2"):
    print("Syntax OK")
```

---

## Referência da API Bridge

Todas as rotas em `http://localhost:19283`.

### `POST /send` — Comandos UNC

Envia JSON `{"c": "<comando>", "p": "<path>", "v": "<valor>"}`.

| Comando | Descrição |
|---------|-----------|
| `clt` | Identidade do cliente → `SYNTAX-v1` |
| `hw` | Hardware ID → `SN-SYNTAX-PY` |
| `rf` | `readfile` — lê arquivo do workspace |
| `wf` | `writefile` (string) — escreve conteúdo no workspace |
| `lf` | `listfiles` — lista diretório do workspace |
| `df` | `delfile` — remove arquivo ou pasta |
| `af` | `appendfile` — adiciona conteúdo ao final do arquivo |
| `fe` | `fileexists` — verifica se arquivo existe |
| `gs` | `getscript` — consome script da fila de execução |

### `POST /writefile?p=<path>` — Escrita binária

Body é o conteúdo raw do arquivo.

### `POST /execute` — Enfileirar script

Body = código Luau raw. Retorna `Queued`.

### `GET /queue/count` — Tamanho da fila

### `POST /queue/clear` — Limpar fila

---

## Build (distribuição)

```powershell
pip install pyinstaller
pyinstaller --clean app.spec
```

O executável será gerado em `dist/SyntaxExecutor.exe` (~15-20 MB com UPX).

---

## Notas Técnicas

- **Compilador:** O projeto inclui um compilador Luau em Python puro (`third_party/luau/`). Se o DLL nativo do Luau estiver presente no diretório, ele é usado automaticamente (mais rápido e 100% compliant).
- **Offsets:** Sempre mantenha `NewestOffsets.txt` atualizado com a versão do Roblox que você está usando. O `Updater.py` pode buscar offsets atualizados da rede.
- **Segurança de Memória:** A alocação remota usa `pymem.allocate()` que chama `VirtualAllocEx`. O bytecode é escrito diretamente no espaço de memória do processo alvo.

---

## Licença

Este projeto é fornecido apenas para fins educacionais. O uso indevido em servidores públicos viola os Termos de Serviço do Roblox.
