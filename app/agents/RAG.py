"""POC do RAG: valida a conexão com o LLM da Groq via LangChain."""

import subprocess
import sys

from dotenv import load_dotenv


'''
def install_package(package: str) -> None:
    """Instala um pacote via pip no mesmo ambiente Python em execução."""
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])
'''

'''
Instalação em runtime apenas para a POC; no MVP, usar requirements.txt.
install_package("pypdf")  # leitura de PDFs
install_package("langchain")  # orquestração de LLMs
install_package("langchain-community")  # loaders e vector stores
install_package("langchain-groq")  # cliente da Groq
install_package("langchain-huggingface")  # embeddings
install_package("langgraph")  # orquestração de agentes
'''

from langchain_groq import ChatGroq  # noqa: E402 - importado após instalação

# Carrega GROQ_API_KEY do arquivo .env.
load_dotenv()

llm = ChatGroq(model="openai/gpt-oss-20b")

# Teste de conectividade com o modelo.
# resposta = llm.invoke("Quais os benefícios de ir a Marte?")
# print(resposta.content)

# url = 