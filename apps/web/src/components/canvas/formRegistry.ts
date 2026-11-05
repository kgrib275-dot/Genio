// 단계 설정 폼에 넘기는 rjsf 위젯·필드·버튼 묶음
import type { RegistryFieldsType, RegistryWidgetsType, TemplatesType } from "@rjsf/utils";
import {
  AddButton,
  AppWidget,
  CodeWidget,
  CopyButton,
  MoveDownButton,
  MoveUpButton,
  NoSubmitButton,
  RemoveButton,
  ConnectorActionWidget,
  ConnectorWidget,
  CredentialWidget,
  DataTableWidget,
  JsonField,
  KbWidget,
  TextareaWidget,
  ValueTextWidget,
} from "@/components/canvas/widgets";
import {
  ApiOperationWidget,
  ApiParamsField,
  ApiToolSetWidget,
  McpArgsField,
  McpServerWidget,
  McpToolWidget,
} from "@/components/canvas/toolWidgets";

export const nodeWidgets: RegistryWidgetsType = {
  // 기본 한 줄 칸도 '값 끌어오기'를 쓴다
  TextWidget: ValueTextWidget,
  textarea: TextareaWidget,
  code: CodeWidget,
  kb: KbWidget,
  connector: ConnectorWidget,
  credential: CredentialWidget,
  connectorAction: ConnectorActionWidget,
  app: AppWidget,
  dataTable: DataTableWidget,
  // v0.8 외부 도구
  mcpServer: McpServerWidget,
  mcpTool: McpToolWidget,
  apiToolSet: ApiToolSetWidget,
  apiOperation: ApiOperationWidget,
};

export const nodeFields: RegistryFieldsType = {
  json: JsonField,
  mcpArgs: McpArgsField,
  apiParams: ApiParamsField,
};

export const nodeTemplates: Partial<TemplatesType> = {
  ButtonTemplates: {
    AddButton,
    RemoveButton,
    MoveUpButton,
    MoveDownButton,
    CopyButton,
    SubmitButton: NoSubmitButton,
  },
};
