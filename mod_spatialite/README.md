# SpatiaLite Binaries

Папка для хранения бинарных файлов SpatiaLite (mod_spatialite.dll для Windows x64).

## 📦 Содержимое

Эта папка должна содержать:

```
mod_spatialite/
├── mod_spatialite.dll          # или mod_spatialite_x64.dll (основной файл)
├── mod_spatialite_x64.dll      # x64 версия (опционально)
├── mod_spatialite_x86.dll      # x86 версия (опционально)
├── iconv.dll                   # Зависимость для Windows
├── zlib1.dll                   # Зависимость для Windows
└── README.md                   # Этот файл
```

## 🚀 Быстрый старт

### Windows x64

1. **Скачать готовые бинарники** с [GitHub Releases](https://github.com/albertomo/SpatiaLite-Win-x64/releases)
   - Найти последний релиз `mod_spatialite-*-win-amd64`
   - Скачать архив

2. **Распаковать файлы** в папку `mod_spatialite/`:
   ```
   mod_spatialite.dll      (или mod_spatialite_x64.dll)
   iconv.dll
   zlib1.dll
   ```

3. **Готово!** Сервер автоматически загрузит библиотеки при запуске

### Linux x64

```bash
# Ubuntu/Debian
sudo apt-get install libspatialite-dev libspatialite7

# Red Hat/CentOS
sudo yum install spatialite-libs spatialite-devel

# Скопировать файл
sudo find /usr -name "mod_spatialite.so" 2>/dev/null
# Копируем найденный файл в mod_spatialite/
cp /path/to/mod_spatialite.so ./mod_spatialite/
```

### macOS

```bash
# Установить через Homebrew
brew install spatialite

# Найти файл
otool -L $(brew --prefix)/lib/mod_spatialite.dylib

# Скопировать
cp $(brew --prefix)/lib/mod_spatialite.dylib ./mod_spatialite/
```

## 📝 Установка mod_spatialite вручную

### Вариант 1: OSGeo4W (Рекомендуется для Windows)

```bash
# 1. Загрузить OSGeo4W с https://trac.osgeo.org/osgeo4w/
# Выбрать установку для x64

# 2. При установке выбрать:
#    - spatialite
#    - spatialite-tools

# 3. Скопировать файлы
xcopy "C:\OSGeo4W64\bin\mod_spatialite.dll" ".\mod_spatialite\"
xcopy "C:\OSGeo4W64\bin\iconv.dll" ".\mod_spatialite\"
xcopy "C:\OSGeo4W64\bin\zlib1.dll" ".\mod_spatialite\"
```

### Вариант 2: Компиляция из исходников

#### Требования для Windows x64

- Visual Studio 2019+ с MSVC compiler
- CMake 3.15+
- Git

#### Сборка

```bash
# 1. Клонировать репозиторий
git clone https://github.com/albertomo/SpatiaLite-Win-x64.git
cd SpatiaLite-Win-x64

# 2. Создать папку сборки
mkdir build
cd build

# 3. Сконфигурировать для x64
cmake .. -G "Visual Studio 16 2019" -A x64

# 4. Компилировать
cmake --build . --config Release

# 5. Копировать файлы
cp bin/Release/mod_spatialite.dll ../../../mod_spatialite/
cp bin/Release/iconv.dll ../../../mod_spatialite/
cp bin/Release/zlib1.dll ../../../mod_spatialite/
```

## 🔧 Использование в коде

```python
from DataSource.spatialite_loader import load_spatialite, verify_spatialite
import sqlite3

# Создать соединение с БД
conn = sqlite3.connect('data.db')

# Загрузить SpatiaLite
if load_spatialite(conn):
    print("✓ SpatiaLite загружен успешно")
    
    # Проверить функциональность
    if verify_spatialite(conn):
        print("✓ SpatiaLite готов к использованию")
        
        # Использовать пространственные функции
        cursor = conn.execute("SELECT spatialite_version()")
        version = cursor.fetchone()[0]
        print(f"Версия: {version}")
else:
    print("✗ Не удалось загрузить SpatiaLite")
```

## 🧪 Проверка версии SpatiaLite

```sql
SELECT spatialite_version();
```

Типичный вывод:
```
5.0.1
```

## ❌ Ошибки и решения

### Ошибка: "the specified module could not be found"

**Причина:** Отсутствуют зависимости (iconv.dll, zlib1.dll)

**Решение:** 
- Убедитесь, что все файлы копированы в папку `mod_spatialite/`:
  - ✓ mod_spatialite.dll
  - ✓ iconv.dll
  - ✓ zlib1.dll
- Проверьте, что это x64 версии (если используете Python x64)

### Ошибка: "DLL load failed while importing _sqlite3"

**Причина:** SQLite не скомпилирован с поддержкой load_extension

**Решение:** 
- Переустановить Python из [microsoft store](https://www.microsoft.com/store/apps/9NCVVGM4FJM3) или [python.org](https://www.python.org/downloads/) (имеют полную поддержку)
- Или установить Python через `conda install python`

### Ошибка: "cannot import name 'spatialite_version' from 'pyspatialite'"

**Причина:** Используется неправильный модуль

**Решение:** Используйте встроенный sqlite3 с расширением mod_spatialite:
```python
import sqlite3  # встроенный модуль
from DataSource.spatialite_loader import load_spatialite

conn = sqlite3.connect('data.db')
load_spatialite(conn)
```

### Ошибка: "SpatiaLite not found"

**Причина:** Папка `mod_spatialite/` не найдена или пуста

**Решение:**
1. Создайте папку `mod_spatialite/` в корне проекта
2. Поместите туда файлы mod_spatialite.dll и зависимости
3. Проверьте пути в логе:
   ```python
   from DataSource.spatialite_loader import get_spatialite_dir, get_extension_load_path
   print("Директория:", get_spatialite_dir())
   print("Путь расширения:", get_extension_load_path())
   ```

## 📊 Поддерживаемые платформы

| Платформа | Файл | Статус | Версия |
|-----------|------|--------|---------|
| Windows x64 | mod_spatialite.dll | ✅ Активная | 5.0+ |
| Windows x86 | mod_spatialite_x86.dll | ⚠️ Устарело | 4.3+ |
| Linux x64 | mod_spatialite.so | ✅ Активная | 5.0+ |
| macOS x64 | mod_spatialite.dylib | ✅ Активная | 5.0+ |
| macOS ARM64 | mod_spatialite.dylib | ✅ Активная | 5.0+ |

## 🔒 Переменная окружения (опционально)

Если хотите хранить SpatiaLite в другом месте, установите переменную окружения:

```bash
# Windows (cmd)
set SPATIALITE_DIR=C:\spatialite\lib

# Windows (PowerShell)
$env:SPATIALITE_DIR="C:\spatialite\lib"

# Linux/macOS
export SPATIALITE_DIR=/opt/spatialite/lib
```

## 📚 Лицензирование

SpatiaLite распространяется под лицензией **LGPL** (GNU Lesser General Public License).

Подробнее: https://www.gaia-gis.it/fossil/libspatialite/

## 🔗 Ссылки

- [SpatiaLite Official](https://www.gaia-gis.it/fossil/libspatialite/)
- [OSGeo4W](https://trac.osgeo.org/osgeo4w/)
- [SpatiaLite GitHub Releases](https://github.com/albertomo/SpatiaLite-Win-x64/releases)
- [Python sqlite3 Documentation](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.load_extension)

## 💡 Советы

1. **Используйте x64 версию** если у вас Python x64 (что рекомендуется)
2. **Проверьте архитектуру Python:**
   ```python
   import struct
   print("Python архитектура:", struct.calcsize("P") * 8, "бит")
   ```
3. **Держите библиотеки в проекте** для портативности между машинами
4. **Обновляйте SpatiaLite** периодически для новых функций и исправлений

## 🆘 Получить помощь

Если есть проблемы:
1. Проверьте логи в `server.log`
2. Убедитесь, что все зависимости установлены
3. Откройте issue на GitHub с логом ошибки
