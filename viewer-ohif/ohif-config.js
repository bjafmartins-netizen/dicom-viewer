/**
 * Configuração do OHIF Viewer apontando para o Orthanc local.
 *
 * Copie (ou aponte) este arquivo para o build do OHIF:
 *   <build-do-ohif>/app-config.js
 *
 * Ver viewer-ohif/README.md para como gerar o build.
 */
window.config = {
  routerBasename: '/',
  showStudyList: true,
  extensions: [],
  modes: [],
  showWarningMessageForCrossOrigin: false,
  showCPUFallbackMessage: true,

  // Quantos estudos a lista inicial traz
  maxNumberOfWebWorkers: 3,
  omitQuotationForMultipartRequest: true,

  defaultDataSourceName: 'orthanc',
  dataSources: [
    {
      namespace: '@ohif/extension-default.dataSourcesModule.dicomweb',
      sourceName: 'orthanc',
      configuration: {
        friendlyName: 'miniPACS local (Orthanc)',
        name: 'orthanc',

        // Endpoints DICOMweb do Orthanc. Se mudar a porta em pacs/orthanc.json
        // (HttpPort), mude aqui também.
        wadoUriRoot: 'http://localhost:8042/wado',
        qidoRoot: 'http://localhost:8042/dicom-web',
        wadoRoot: 'http://localhost:8042/dicom-web',

        qidoSupportsIncludeField: true,
        supportsReject: true,
        imageRendering: 'wadors',
        thumbnailRendering: 'wadors',
        enableStudyLazyLoad: true,
        supportsFuzzyMatching: false,
        supportsWildcard: true,
        staticWado: false,
        singlepart: false,
        bulkDataURI: { enabled: true },
      },
    },
  ],

  // Sem autenticação: protótipo local com dados anonimizados.
  // Se ligar AuthenticationEnabled no Orthanc, é aqui que entra o header.
  // requestOptions: { auth: 'usuario:senha' },

  hotkeys: undefined, // usa os atalhos padrão do OHIF
};
