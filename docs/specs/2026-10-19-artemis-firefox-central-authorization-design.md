# Artemis — Autorização centralizada e adaptador Firefox

Data: 2026-10-19
Status: proposta para revisão; ainda não implementada.

## 1. Objetivo

Permitir que o Artemis, em ambiente Android/Termux, solicite autorização
explícita antes de abrir uma URL no Firefox. A arquitetura deve permitir
adicionar outros adaptadores posteriormente sem duplicar a política de
permissões.

O modelo local existente deve ser preservado. Esta mudança não autoriza
acesso remoto, chamadas a APIs de modelos externos ou downloads de modelos.

## 2. Princípios de arquitetura

Separar quatro responsabilidades:

1. Planejamento: o Artemis propõe uma ação estruturada.
2. Autorização: um componente central avalia a ação e solicita consentimento.
3. Execução: um adaptador restrito executa somente a ação aprovada.
4. Verificação: o sistema informa o resultado observado e registra o estado
   da operação sem registrar segredos desnecessários.

O modelo não deve poder conceder a própria autorização nem contornar a
camada central executando comandos arbitrários.

## 3. Escopo inicial

A primeira versão deve permitir somente a abertura de URLs HTTP ou HTTPS
no Firefox, usando uma integração Android compatível com o ambiente real.

Fora do escopo inicial:
- clicar em elementos da página;
- ler ou extrair o conteúdo da tela;
- preencher ou enviar formulários;
- baixar arquivos;
- acessar contas, credenciais ou sessões;
- executar comandos arbitrários fornecidos pelo modelo;
- conceder permissões permanentes ou reutilizar aprovação anterior.

## 4. Fluxo de autorização

1. O Artemis propõe uma URL.
2. A política central valida o tipo de ação e a URL.
3. A interface de autorização apresenta a ação e o destino exatos.
4. O usuário aprova explicitamente aquela ação.
5. O adaptador executa somente a ação aprovada.
6. O resultado informa sucesso observado, falha ou cancelamento.

A ausência de resposta, entrada vazia, recusa, erro de validação ou falha
na autorização deve resultar em não execução.

A aprovação é única, vinculada à ação e à URL apresentadas. Alterar a URL
exige nova autorização.

## 5. Interface de autorização

A proposta inicial é um adaptador de aprovação interativo no Termux,
com confirmação explícita, por exemplo: "Autoriza? [s/N]".

Antes da implementação, verificar se o contexto real de execução do Artemis
consegue receber entrada interativa. Se não conseguir, não simular aprovação
nem tratar ausência de entrada como consentimento. Nesse caso, definir um
canal de aprovação compatível e seguro antes de habilitar a execução.

## 6. Integração com Android e Firefox

O adaptador deve:
- validar o esquema e rejeitar URLs inválidas;
- direcionar a abertura explicitamente ao Firefox;
- evitar fallback silencioso para outro navegador;
- não executar se não conseguir validar o destino;
- distinguir solicitação aceita pelo Android de confirmação real de que
  o Firefox abriu a página.

A identificação do pacote do Firefox permanece uma questão técnica em aberto:
um comando Android direcionado a org.mozilla.firefox foi aceito, mas as
listagens de pacotes consultadas não mostraram correspondência. Isso deve
ser investigado antes de escolher o mecanismo definitivo.

## 7. Modo local e isolamento

Preservar ARTEMIS_LOCAL_ONLY=1 e o modelo configurado em
ARTEMIS_LOCAL_MODEL. Não relaxar a política local para habilitar o navegador.

Não modificar o projeto BR-no-GTA, o projeto Hazewave, caches de modelos
ou ambientes virtuais externos ao repositório Artemis.

## 8. Testes de regressão

Criar testes para:
- aprovação explícita permite solicitar a abertura;
- recusa impede a execução;
- entrada vazia ou ausência de resposta impede a execução;
- URL inválida é rejeitada;
- esquema diferente de HTTP/HTTPS é rejeitado;
- alteração da URL exige nova autorização;
- falha na autorização não chama o adaptador;
- falha do adaptador é comunicada como falha, não como sucesso;
- não há fallback silencioso para outro navegador;
- modo local permanece habilitado.

Os testes devem usar dependências simuladas quando apropriado, sem abrir
aplicativos reais nem depender de rede externa.

## 9. Diagnóstico e preservação

Antes de editar código:
- registrar o estado do Git e os arquivos já modificados;
- criar backup verificável dos arquivos que serão alterados;
- inspecionar o mecanismo de registro de ferramentas e o fluxo de execução;
- localizar os testes existentes relevantes.

Não sobrescrever alterações preexistentes. Não fazer commit, push ou merge
sem autorização explícita.

## 10. Critérios de aceitação

A primeira versão só estará pronta quando:
- a autorização central for obrigatória e falhar de forma segura;
- o adaptador executar apenas a URL aprovada;
- o Firefox for o destino validado;
- os testes de regressão relevantes passarem no ambiente suportado;
- as limitações de execução interativa forem documentadas;
- o modo local e as alterações preexistentes permanecerem preservados.

## 11. Decisões ainda necessárias durante a inspeção

- Qual ponto existente do Artemis é o mais seguro para impor a autorização?
- Como o contexto de execução entrega a solicitação ao usuário e recebe a
  resposta sem depender de entrada interativa indisponível?
- Qual mecanismo Android identifica e abre o pacote correto do Firefox?
- Quais testes podem ser executados no ambiente atual sem instalar
  dependências ou modificar outros projetos?
