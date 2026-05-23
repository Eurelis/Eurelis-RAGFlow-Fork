import { zodResolver } from '@hookform/resolvers/zod';
import { useQuery } from '@tanstack/react-query';
import { useCallback, useId, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import { z } from 'zod';

import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

import { listTenants } from '@/services/admin-service';

interface AddToTeamFormData {
  tenantId: string;
}

interface AddToTeamFormProps {
  id: string;
  form: ReturnType<typeof useForm<AddToTeamFormData>>;
  onSubmit?: (data: AddToTeamFormData) => void;
  excludeTenantIds?: string[];
}

export const AddToTeamForm = ({
  id,
  form,
  onSubmit = () => {},
  excludeTenantIds = [],
}: AddToTeamFormProps) => {
  const { t } = useTranslation();

  const { data: tenants = [] } = useQuery({
    queryKey: ['admin/listTenants'],
    queryFn: async () => (await listTenants()).data.data,
    retry: false,
  });

  const availableTenants = tenants.filter(
    (t) => !excludeTenantIds.includes(t.tenant_id),
  );

  return (
    <Form {...form}>
      <form
        id={id}
        onSubmit={form.handleSubmit(onSubmit)}
        className="space-y-6"
      >
        <FormField
          control={form.control}
          name="tenantId"
          render={({ field }) => (
            <FormItem>
              <FormLabel className="text-sm font-medium">
                {t('admin.teams')}
              </FormLabel>
              <FormControl>
                <Select onValueChange={field.onChange} value={field.value}>
                  <SelectTrigger className="w-full h-10">
                    <SelectValue placeholder={t('admin.selectTeam')} />
                  </SelectTrigger>
                  <SelectContent className="bg-bg-base">
                    <SelectGroup>
                      {availableTenants.length > 0 ? (
                        availableTenants.map((tenant) => (
                          <SelectItem
                            key={tenant.tenant_id}
                            value={tenant.tenant_id}
                          >
                            {tenant.owner_email}
                            {tenant.owner_nickname
                              ? ` (${tenant.owner_nickname})`
                              : ''}
                          </SelectItem>
                        ))
                      ) : (
                        <div className="text-text-secondary px-2 py-6 text-sm text-center">
                          {t('common.noData')}
                        </div>
                      )}
                    </SelectGroup>
                  </SelectContent>
                </Select>
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      </form>
    </Form>
  );
};

function useAddToTeamForm() {
  const { t } = useTranslation();
  const id = useId();

  const schema = useMemo(
    () =>
      z.object({
        tenantId: z.string().min(1, { message: t('admin.selectTeam') }),
      }),
    [t],
  );

  const form = useForm<AddToTeamFormData>({
    defaultValues: { tenantId: '' },
    resolver: zodResolver(schema),
  });

  const FormComponent = useCallback(
    (props: Partial<AddToTeamFormProps>) => (
      <AddToTeamForm id={id} form={form} {...props} />
    ),
    [id, form],
  );

  return { schema, id, form, FormComponent };
}

export default useAddToTeamForm;
