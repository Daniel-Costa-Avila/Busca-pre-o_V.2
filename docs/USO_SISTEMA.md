# Manual - Uso do Sistema (Guia para apresentacao)

Este manual explica como utilizar o sistema de pesquisa de precos, de forma simples e passo a passo.

## 1. O que o sistema faz
- Recebe uma planilha com produtos.
- Pesquisa os precos nos canais suportados.
- Gera uma planilha de saida unificada.

## 2. Estrutura da planilha de entrada
A planilha de entrada deve ter estas colunas basicas:
- Coluna A: id no Canal
- Coluna B: CODIGO INTERNO
- Coluna C: Canal
- Coluna D: Titulo
- Coluna E: Preco (antes era A prazo)
- Coluna F: Link

Observacao importante:
- As colunas A e B sao preservadas exatamente como na entrada.
- Se a coluna A estiver vazia, ela sera preenchida com B + C.

## 3. Como iniciar uma pesquisa manual pelo painel
1. Abra o painel local.
2. Clique em "Execucao Manual".
3. Envie a planilha .xlsx.
4. Clique em "Iniciar Coleta".
5. Acompanhe o status na aba "Status do Job".

## 4. Como iniciar a pesquisa via Google Drive
Veja o manual especifico em:
- docs\USO_PESQUISA_VIA_DRIVE.md

## 5. Onde o resultado final e salvo
O resultado sempre fica no caminho fixo:
- C:\Users\daniel.avila\Desktop\AGENTE_DE_PRECOS\Resultado Diario\Busca-Preco_DDMMYYYY.xlsx

Esse arquivo e sobrescrito a cada nova execucao.

## 6. Regras de consolidacao
- A planilha de saida ja vem unificada com a planilha secundaria (Relatorio_Financeiro).
- O arquivo final gera duas abas: `Output` e `Consolidado`.
- A aba `Consolidado` traz `LOJA MENOR PREÇO`, `SELLER MENOR PREÇO`, `MENOR PRECO`, `PREÇO MÉDIO` e `QUANTIDADE DE LOJAS`.
- A coluna de preco se chama `Preco`.

## 7. Canais suportados (exemplos)
- Magazine Luiza
- Casas Bahia
- Mercado Livre
- Carrefour
- Zema
- Web Continental
- Madeiramadeira

## 8. Como validar se o job concluiu
- No painel, verifique o status como "DONE".
- No sistema de arquivos, confirme se o arquivo do resultado foi atualizado.

## 9. Problemas comuns e solucao simples
1. Erro de credencial
   - Verifique se as variaveis do .env estao configuradas.

2. Nenhum resultado
   - Verifique se os links estao corretos.
   - Verifique se o canal esta reconhecido.

3. Planilha nao atualiza
   - Confira se o job terminou.
   - Verifique se o arquivo foi sobrescrito.

## 10. Dicas para apresentacao
- Mostre o fluxo: Entrada -> Processamento -> Saida.
- Destaque que a planilha final ja vem unificada.
- Explique que o resultado sobrescreve o arquivo do dia anterior.
- Mostre que a coluna A e B sao preservadas.

Fim.
