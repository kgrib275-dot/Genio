// 노드 설정 폼에 넘기는 rjsf 위젯·필드·버튼 묶음
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
} from "@/components/canvas/widgets";

export const nodeWidgets: RegistryWidgetsType = {
  textarea: TextareaWidget,
  code: CodeWidget,
  kb: KbWidget,
  connector: ConnectorWidget,
  credential: CredentialWidget,
  connectorAction: ConnectorActionWidget,
  app: AppWidget,
  dataTable: DataTableWidget,
};

export const nodeFields: RegistryFieldsType = { json: JsonField };

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
