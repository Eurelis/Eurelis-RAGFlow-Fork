'use client';

import { AvatarNameDescription } from '@/components/avatar-name-description';
import { KnowledgeBaseFormField } from '@/components/knowledge-base-item';
import { LlmSettingFieldItems } from '@/components/llm-setting-items/next';
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Textarea } from '@/components/ui/textarea';
import { useTranslate } from '@/hooks/common-hooks';
import { PermissionFormField } from '@/pages/dataset/dataset-setting/permission-form-field';
import { getDirAttribute } from '@/utils/text-direction';
import { useFormContext, useWatch } from 'react-hook-form';

export default function ChatBasicSetting() {
  const { t } = useTranslate('chat');
  const form = useFormContext();

  const prologueValue = useWatch({
    control: form.control,
    name: 'prompt_config.prologue',
  });

  const emptyResponseValue = useWatch({
    control: form.control,
    name: 'prompt_config.empty_response',
  });

  return (
    <div className="space-y-8">
      <AvatarNameDescription />
      <LlmSettingFieldItems
        prefix="llm_setting"
        llmId="llm_id"
        showCollapse
      ></LlmSettingFieldItems>
      <PermissionFormField />
      <FormField
        control={form.control}
        name={'prompt_config.empty_response'}
        render={({ field }) => (
          <FormItem>
            <FormLabel tooltip={t('emptyResponseTip')}>
              {t('emptyResponse')}
            </FormLabel>
            <FormControl>
              <Textarea
                {...field}
                placeholder={t('emptyResponsePlaceholder')}
                dir={getDirAttribute(emptyResponseValue || '')}
              ></Textarea>
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name={'prompt_config.prologue'}
        render={({ field }) => (
          <FormItem>
            <FormLabel tooltip={t('setAnOpenerTip')}>
              {t('setAnOpener')}
            </FormLabel>
            <FormControl>
              <Textarea
                {...field}
                dir={getDirAttribute(prologueValue || '')}
              ></Textarea>
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <KnowledgeBaseFormField></KnowledgeBaseFormField>
    </div>
  );
}
