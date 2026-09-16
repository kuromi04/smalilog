# Referencia de API Smali

Esta guía documenta la clase incluida en el payload:

```smali
Lcom/deadnote/RemoteLogger;
```

Úsala únicamente en APKs propios o cuando tengas autorización expresa para analizarlos.

## Requisitos de integración

1. Incluye `RemoteLogger` en el DEX de la APK.
2. Copia `liblogger.so` en `lib/arm64-v8a/`.
3. Inicia el receptor local con `smalilog server`.
4. Aumenta `.registers` antes de usar registros temporales nuevos.

La biblioteca se carga con `System.loadLibrary("logger")`. Si no se puede cargar, los hooks `hookEnter` y `hookExit` no emiten eventos.

## Métodos disponibles

| Método Java | Firma Smali | Evento enviado |
|---|---|---|
| `d(String, String)` | `d(Ljava/lang/String;Ljava/lang/String;)V` | `DEBUG`, tag indicado |
| `hookEnter(String, String, Object)` | `hookEnter(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Object;)V` | `DEBUG`, tag `HOOK_ENTER` |
| `hookExit(String, Object)` | `hookExit(Ljava/lang/String;Ljava/lang/Object;)V` | `DEBUG`, tag `HOOK_EXIT` |

Todos son `static`, devuelven `void` y se invocan con `invoke-static`.

## Log personalizado: `d`

```smali
const-string v0, "AUTH"
const-string v1, "Token solicitado"
invoke-static {v0, v1}, Lcom/deadnote/RemoteLogger;->d(Ljava/lang/String;Ljava/lang/String;)V
```

No uses registros que contengan valores vivos sin preservarlos. Si la función tiene `.registers 2`, reserva registros adicionales, por ejemplo `.registers 4`, y utiliza los nuevos temporales.

## Hook de entrada: `hookEnter`

El tercer argumento debe ser una referencia (`Ljava/lang/Object;`). Para objetos, strings y arrays puede pasarse directamente:

```smali
const-string v0, "com.example.Login#submit"
const-string v1, "username"
invoke-static {v0, v1, p1}, Lcom/deadnote/RemoteLogger;->hookEnter(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Object;)V
```

Para primitivos, conviértelos a su wrapper antes de invocar. Ejemplo con `int`:

```smali
invoke-static {p1}, Ljava/lang/Integer;->valueOf(I)Ljava/lang/Integer;
move-result-object v2
const-string v0, "com.example.Counter#set"
const-string v1, "value"
invoke-static {v0, v1, v2}, Lcom/deadnote/RemoteLogger;->hookEnter(Ljava/lang/String;Ljava/lang/String;Ljava/lang/Object;)V
```

Wrappers habituales: `Integer.valueOf(I)`, `Long.valueOf(J)`, `Boolean.valueOf(Z)`, `Float.valueOf(F)` y `Double.valueOf(D)`. Los tipos `long` y `double` consumen dos registros.

## Hook de salida: `hookExit`

Para métodos que retornan una referencia, inserta el hook después de `move-result-object` y antes de `return-object`:

```smali
invoke-virtual {p0}, Lcom/example/Service;->load()Ljava/lang/String;
move-result-object v0
const-string v1, "com.example.Service#load"
invoke-static {v1, v0}, Lcom/deadnote/RemoteLogger;->hookExit(Ljava/lang/String;Ljava/lang/Object;)V
return-object v0
```

Para `return-void`, registra `null`:

```smali
const-string v0, "com.example.App#start"
const/4 v1, 0x0
invoke-static {v0, v1}, Lcom/deadnote/RemoteLogger;->hookExit(Ljava/lang/String;Ljava/lang/Object;)V
return-void
```

Para retornos primitivos, conserva el valor, conviértelo a wrapper y pásalo al hook antes del `return` correspondiente.

## Registros y parámetros

- En métodos de instancia, `p0` es `this` y los argumentos comienzan en `p1`.
- En métodos estáticos, los argumentos comienzan en `p0`.
- Al aumentar `.registers`, los alias `pN` siguen siendo la forma más segura de referirse a parámetros.
- `vN` son temporales. No sobrescribas registros que se usen después del hook.

Antes de modificar un archivo, usa:

```bash
smalilog hook analyze Archivo.smali -m NombreMetodo --sig '(I)V'
```

Después de inyectar, recompila, firma y prueba la APK en un entorno autorizado.
