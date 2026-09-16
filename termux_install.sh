#!/bin/bash
# Instalación de smalilog en Termux
# Ejecutar como root o con sudo en Termux

echo "Instalando dependencias..."
pkg update && pkg install python git openssl -y

echo "Creando entorno virtual..."
python -m venv $HOME/smalilog-venv
source $HOME/smalilog-venv/bin/activate

echo "Instalando smalilog..."
pip install websockets cryptography

echo "Clonando repositorio..."
cd $HOME
git clone https://github.com/1jehuang/smalilog.git
cd smalilog

echo "Instalando smalilog..."
pip install -e .

echo "Instalación completada."
echo "Para usar smalilog, ejecuta: smalilog"
echo "Para el servidor: smalilog server"
echo "Para el cliente: smalilog listen"
echo "Para el menú: smalilog menu"
echo "Para ver la ayuda: smalilog --help"
echo ""
echo "Documentación completa: cat README.md"