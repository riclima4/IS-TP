# Imagem base do Python
FROM python:3.9-slim

# Diretório de trabalho no container
WORKDIR /app

# Copia o arquivo de dependências (se tiver um requirements.txt)
COPY requirements.txt /app/

# Instala as dependências
RUN pip install --no-cache-dir -r requirements.txt

# Copia todo o código da aplicação para dentro do container
COPY . /app/

# Expõe a porta 8000 para o servidor XML-RPC
EXPOSE 8000

# Comando para rodar o servidor quando o container for iniciado
CMD ["python", "app.py"]
