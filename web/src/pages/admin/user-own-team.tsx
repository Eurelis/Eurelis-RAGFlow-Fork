import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router';

import {
  LucideArrowLeft,
  LucideCheckCircle,
  LucideDot,
  LucidePlus,
  LucideTrash2,
} from 'lucide-react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table';

import { Routes } from '@/routes';

import { RAGFlowAvatar } from '@/components/ragflow-avatar';
import Spotlight from '@/components/spotlight';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

import { TableEmpty } from '@/components/table-skeleton';
import {
  addTenantMember,
  getUserDetails,
  listTenantMembers,
  listUsers,
  removeTenantMember,
  updateTenantMemberRole,
} from '@/services/admin-service';
import EnterpriseFeature from './components/enterprise-feature';
import { parseBooleanish } from './utils';

const columnHelper = createColumnHelper<AdminService.TenantMember>();

function AdminUserOwnTeam() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { id } = useParams();
  const queryClient = useQueryClient();

  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState('');

  const { data: detail } = useQuery({
    queryKey: ['admin/userDetail', id],
    queryFn: async () => {
      const res = await getUserDetails(id!);
      return res.data.data[0];
    },
    enabled: !!id,
    retry: false,
  });

  const { data: members = [] } = useQuery({
    queryKey: ['admin/tenantMembers', detail?.id],
    queryFn: async () => (await listTenantMembers(detail!.id)).data.data,
    enabled: !!detail?.id,
    retry: false,
  });

  const { data: allUsers = [] } = useQuery({
    queryKey: ['admin/listUsers'],
    queryFn: async () => (await listUsers()).data.data,
    retry: false,
  });

  const removeMutation = useMutation({
    mutationFn: (userId: string) => removeTenantMember(detail!.id, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['admin/tenantMembers', detail?.id],
      });
      queryClient.invalidateQueries({ queryKey: ['admin/listTenants'] });
    },
  });

  const validateInviteMutation = useMutation({
    mutationFn: (userId: string) =>
      updateTenantMemberRole(detail!.id, userId, 'normal'),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['admin/tenantMembers', detail?.id],
      });
    },
  });

  const addMutation = useMutation({
    mutationFn: (userId: string) =>
      addTenantMember(detail!.id, userId, 'normal'),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['admin/tenantMembers', detail?.id],
      });
      queryClient.invalidateQueries({ queryKey: ['admin/listTenants'] });
      setAddDialogOpen(false);
      setSelectedUserId('');
    },
  });

  const existingUserIds = new Set(members.map((m) => m.user_id));
  const availableUsers = allUsers.filter(
    (u) => u.id !== detail?.id && !existingUserIds.has(u.id),
  );

  const columnDefs = useMemo(
    () => [
      columnHelper.accessor('email', {
        header: t('admin.email'),
        cell: ({ row, cell }) => (
          <div className="flex items-center gap-2">
            <RAGFlowAvatar
              avatar={row.original.avatar}
              name={cell.getValue()}
            />
            <div className="flex flex-col">
              <span>{cell.getValue()}</span>
              {row.original.nickname && (
                <span className="text-xs text-text-secondary">
                  {row.original.nickname}
                </span>
              )}
            </div>
          </div>
        ),
      }),
      columnHelper.accessor('role', {
        header: t('admin.teamMemberRole'),
        cell: ({ cell }) => (
          <Badge variant="secondary">{cell.getValue()}</Badge>
        ),
      }),
      columnHelper.accessor('update_date', {
        header: t('admin.addedDate'),
      }),
      columnHelper.display({
        id: 'actions',
        header: t('admin.actions'),
        cell: ({ row }) => (
          <div className="flex items-center gap-1">
            {row.original.role === 'invite' && (
              <Button
                variant="ghost"
                size="icon"
                title={t('admin.validateInvite')}
                onClick={() =>
                  validateInviteMutation.mutate(row.original.user_id)
                }
              >
                <LucideCheckCircle className="size-4" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="text-destructive hover:text-destructive"
              onClick={() => removeMutation.mutate(row.original.user_id)}
            >
              <LucideTrash2 className="size-4" />
            </Button>
          </div>
        ),
      }),
    ],
    [t, removeMutation, validateInviteMutation],
  );

  const table = useReactTable({
    data: members,
    columns: columnDefs,
    getCoreRowModel: getCoreRowModel(),
    enableSorting: false,
  });

  return (
    <section className="px-10 py-5 size-full flex flex-col">
      <nav className="mb-5">
        <Button
          variant="outline"
          className="h-10 px-3 dark:bg-bg-input dark:border-border-button"
          onClick={() => navigate(`${Routes.AdminUserManagement}`)}
        >
          <LucideArrowLeft />
          <span>{t('admin.back')}</span>
        </Button>
      </nav>

      <Card className="!shadow-none relative h-0 basis-0 grow flex flex-col bg-transparent border-0.5 border-border-button overflow-hidden">
        <Spotlight />

        <CardHeader className="pb-6 border-b-0.5 dark:border-border-button space-y-8">
          <h1 className="text-xl font-semibold">{t('setting.teamMembers')}</h1>

          <section className="flex items-center justify-between">
            <div className="flex items-center gap-4 text-base">
              <RAGFlowAvatar
                avatar={detail?.avatar}
                name={detail?.email}
                isPerson
              />
              <span>{detail?.email}</span>
              <Badge
                variant={
                  parseBooleanish(detail?.is_active) ? 'success' : 'destructive'
                }
                className="pl-[.5em]"
              >
                <LucideDot className="size-[1em] stroke-[8] mr-1" />
                {t(
                  parseBooleanish(detail?.is_active)
                    ? 'admin.active'
                    : 'admin.inactive',
                )}
              </Badge>
              <EnterpriseFeature>
                {() =>
                  detail?.role && (
                    <Badge variant="secondary">{detail?.role}</Badge>
                  )
                }
              </EnterpriseFeature>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="gap-2"
              onClick={() => setAddDialogOpen(true)}
            >
              <LucidePlus className="size-4" />
              {t('admin.addToTeam')}
            </Button>
          </section>
        </CardHeader>

        <CardContent className="h-0 basis-0 grow pt-4">
          <ScrollArea className="h-full">
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <TableHead key={header.id}>
                        {header.isPlaceholder
                          ? null
                          : flexRender(
                              header.column.columnDef.header,
                              header.getContext(),
                            )}
                      </TableHead>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {table.getRowModel().rows?.length ? (
                  table.getRowModel().rows.map((row) => (
                    <TableRow key={row.id}>
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id}>
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext(),
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : (
                  <TableEmpty columnsLength={columnDefs.length} />
                )}
              </TableBody>
            </Table>
          </ScrollArea>
        </CardContent>
      </Card>

      <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('admin.addToTeam')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium block mb-2">
                {t('admin.user')}
              </label>
              <Select value={selectedUserId} onValueChange={setSelectedUserId}>
                <SelectTrigger>
                  <SelectValue placeholder={t('admin.selectUser')} />
                </SelectTrigger>
                <SelectContent>
                  {availableUsers.map((u) => (
                    <SelectItem key={u.id} value={u.id}>
                      {u.email}
                      {u.nickname ? ` (${u.nickname})` : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddDialogOpen(false)}>
              {t('admin.cancel')}
            </Button>
            <Button
              disabled={!selectedUserId || addMutation.isPending}
              onClick={() => addMutation.mutate(selectedUserId)}
            >
              {t('admin.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

export default AdminUserOwnTeam;
