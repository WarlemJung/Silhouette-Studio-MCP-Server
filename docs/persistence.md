# Persistência Transacional e Recuperação

Este documento descreve as garantias de persistência, controle de concorrência e recuperação contra falhas implementadas no pacote `silhouette_mcp.persistence`.

## Módulos Envolvidos

- `src/silhouette_mcp/persistence/storage.py`: lock interprocesso, caminhos normalizados por slug, escrita atômica com `os.fsync`, substituição segura com backoff e limpeza de temporários órfãos.
- `src/silhouette_mcp/persistence/repository.py`: preparação transacional de payload, validação de esquema antes de tocar no disco, backup preventivo e recuperação automática ao carregar.
- `src/silhouette_mcp/persistence/__init__.py`: fachada de exportação do subsistema de persistência.

## Controle de Concorrência (`_InterProcessLock`)

Todas as leituras e gravações de projeto utilizam o singleton reentrante `_LOCK` (`_InterProcessLock`):

1. **Serialização intra-processo**: `threading.RLock()` garante reentrância segura quando serviços adquirem `_LOCK` externamente ao ciclo `load_design` -> alteração -> `save_design`.
2. **Exclusão mútua interprocesso**: um arquivo `.silhouette.lock` em `OUTPUT_DIR` recebe trava não bloqueante em loop controlado até `LOCK_TIMEOUT_S`:
   - **Windows**: `msvcrt.locking(..., LK_NBLCK / LK_UNLCK)`.
   - **POSIX / Linux**: `fcntl.flock(..., LOCK_EX | LOCK_NB / LOCK_UN)`.
3. Em caso de timeout ou falha na aquisição, `SilhouetteRuntimeError` é levantada e qualquer descritor aberto é fechado sem vazamento de lock.

## Fluxo Transacional de Escrita (`_save`)

1. **Validação e serialização estrita (`_prepare_save_payload`)**:
   - Valida uma cópia rasa do documento via `_validate_design_dict` antes de alterar `d["revision"]` ou acessar o disco.
   - Calcula `next_rev`, revalida o documento candidato e serializa com `json.dumps(candidate, indent=1, allow_nan=False)`, rejeitando `NaN`/`Infinity` e esquemas inválidos antes de qualquer I/O.
2. **Higienização de temporários (`_cleanup_stale_temp_files`)**:
   - Remove arquivos `*.tmp` regulares (não symlinks) com idade superior a `max_age_s` (padrão `3600.0` segundos) deixados por encerramentos abruptos anteriores.
3. **Preservação preventiva do backup (`_preserve_existing_backup`)**:
   - Se o arquivo primário (`<slug>.design.json`) já existe e é válido, mas `<slug>.design.json.bak` ainda não existe, grava uma cópia atômica do primário anterior em `.bak` antes de substituí-lo.
4. **Escrita atômica no primário**:
   - Cria arquivo temporário no mesmo diretório (`OUTPUT_DIR`, evitando rename entre volumes diferentes), escreve o payload UTF-8, executa `flush()` + `os.fsync(tf.fileno())` e substitui o alvo via `_atomic_replace` (com backoff em `PermissionError` transitório).
   - **Rollback em memória e disco**: qualquer falha antes ou durante `_atomic_replace` remove o arquivo temporário e **não** altera `d["revision"]`, mantendo em memória e no disco o estado consistente anterior.
5. **Commit da revisão e atualização do `.bak`**:
   - Somente após `_atomic_replace` concluir é que `d["revision"] = next_rev` é aplicado em memória.
   - O arquivo `<slug>.design.json.bak` é então atualizado atomicamente via `_atomic_write_file(..., ".bak.tmp", ...)`; uma falha isolada nessa etapa gera `logger.warning`, preservando o primário já comitado e o `.bak` anterior.

## Recuperação Automática (`_load`)

1. Tenta ler e validar `<slug>.design.json` com `_validate_design_dict`.
2. Se o primário estiver ausente, corrompido ou inválido, lê e valida `<slug>.design.json.bak`.
3. Quando o backup é válido, cura o arquivo primário automaticamente por meio de `_atomic_write_file(..., ".rec.tmp", ...)` (com `os.fsync`) e registra um warning estruturado.
4. Se ambos estiverem ausentes/corrompidos ou se a restauração do primário falhar em disco, lança `SilhouetteValueError` explícita sem retornar estado parcial.

## Garantias e Limitações entre Sistemas Operacionais

| Aspecto | Windows (`NTFS` / `ReFS`) | Linux / POSIX (`ext4` / `xfs`) |
|---|---|---|
| Lock interprocesso | `msvcrt.locking` em `.silhouette.lock` | `fcntl.flock` em `.silhouette.lock` |
| Flush de arquivo | `flush()` + `os.fsync(fd)` antes do `os.replace` | `flush()` + `os.fsync(fd)` antes do `os.replace` |
| Contenção de antivírus / indexador | Retry automático em `PermissionError` no `_atomic_replace` | Substituição POSIX atômica dentro do mesmo diretório |
| Diretório `fsync` | Não aplicável via POSIX `fsync` de diretório | `os.fsync` aplicado ao arquivo; durabilidade da entrada de diretório depende das barreiras de metadados do filesystem |

