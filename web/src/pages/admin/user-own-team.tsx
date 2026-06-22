// Eurelis — page admin de gestion des équipes d'un utilisateur (vue propriétaire).
// Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router';

import {
  LucideArrowLeft,
  LucideCheckCircle,
  LucideChevronLeft,
  LucideChevronRight,
  LucideDot,
} from 'lucide-react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Routes } from '@/routes';

import { RAGFlowAvatar } from '@/components/ragflow-avatar';
import Spotlight from '@/components/spotlight';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';

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

function matchFilter(query: string) {
  const q = query.toLowerCase().trim();
  return (item: { email: string; nickname?: string | null }) =>
    !q ||
    item.email.toLowerCase().includes(q) ||
    (item.nickname ?? '').toLowerCase().includes(q);
}

type OutsideUser = {
  id: string;
  email: string;
  nickname?: string | null;
  avatar?: string | null;
};

function OutsideUserRow({
  user,
  checked,
  onToggle,
}: {
  user: OutsideUser;
  checked: boolean;
  onToggle: (id: string) => void;
}) {
  return (
    <div
      className="flex items-center gap-3 px-3 py-2 rounded-md cursor-pointer hover:bg-accent/50 transition-colors"
      onClick={() => onToggle(user.id)}
    >
      <Checkbox
        checked={checked}
        onCheckedChange={() => onToggle(user.id)}
        onClick={(e) => e.stopPropagation()}
      />
      <RAGFlowAvatar avatar={user.avatar ?? undefined} name={user.email} />
      <div className="flex flex-col min-w-0 grow">
        <span className="text-sm truncate">{user.email}</span>
        {user.nickname && (
          <span className="text-xs text-text-secondary truncate">
            {user.nickname}
          </span>
        )}
      </div>
    </div>
  );
}

function MemberRow({
  member,
  checked,
  onToggle,
  onValidate,
}: {
  member: AdminService.TenantMember;
  checked: boolean;
  onToggle: (id: string) => void;
  onValidate: (id: string) => void;
}) {
  return (
    <div
      className="flex items-center gap-3 px-3 py-2 rounded-md cursor-pointer hover:bg-accent/50 transition-colors"
      onClick={() => onToggle(member.user_id)}
    >
      <Checkbox
        checked={checked}
        onCheckedChange={() => onToggle(member.user_id)}
        onClick={(e) => e.stopPropagation()}
      />
      <RAGFlowAvatar avatar={member.avatar} name={member.email} />
      <div className="flex flex-col min-w-0 grow">
        <span className="text-sm truncate">{member.email}</span>
        {member.nickname && (
          <span className="text-xs text-text-secondary truncate">
            {member.nickname}
          </span>
        )}
      </div>
      <div
        className="flex items-center gap-1 shrink-0"
        onClick={(e) => e.stopPropagation()}
      >
        {member.role !== 'normal' && (
          <Badge variant="secondary" className="text-xs">
            {member.role}
          </Badge>
        )}
        {member.role === 'invite' && (
          <Button
            variant="ghost"
            size="icon"
            className="size-6"
            onClick={() => onValidate(member.user_id)}
          >
            <LucideCheckCircle className="size-3.5" />
          </Button>
        )}
      </div>
    </div>
  );
}

function AdminUserOwnTeam() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { id } = useParams();
  const queryClient = useQueryClient();

  const [leftFilter, setLeftFilter] = useState('');
  const [rightFilter, setRightFilter] = useState('');
  const [selectedLeft, setSelectedLeft] = useState<Set<string>>(new Set());
  const [selectedRight, setSelectedRight] = useState<Set<string>>(new Set());

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

  const invalidateMembers = () => {
    queryClient.invalidateQueries({
      queryKey: ['admin/tenantMembers', detail?.id],
    });
    queryClient.invalidateQueries({ queryKey: ['admin/listTenants'] });
  };

  const addMutation = useMutation({
    mutationFn: async (userIds: string[]) => {
      for (const uid of userIds) {
        await addTenantMember(detail!.id, uid, 'normal');
      }
    },
    onSuccess: () => {
      invalidateMembers();
      setSelectedLeft(new Set());
    },
  });

  const removeMutation = useMutation({
    mutationFn: async (userIds: string[]) => {
      for (const uid of userIds) {
        await removeTenantMember(detail!.id, uid);
      }
    },
    onSuccess: () => {
      invalidateMembers();
      setSelectedRight(new Set());
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

  const existingUserIds = useMemo(
    () => new Set(members.map((m) => m.user_id)),
    [members],
  );

  const outsideUsers = useMemo(
    () =>
      allUsers.filter((u) => u.id !== detail?.id && !existingUserIds.has(u.id)),
    [allUsers, detail?.id, existingUserIds],
  );

  const filteredOutside = useMemo(
    () => outsideUsers.filter(matchFilter(leftFilter)),
    [outsideUsers, leftFilter],
  );

  const filteredMembers = useMemo(
    () => members.filter(matchFilter(rightFilter)),
    [members, rightFilter],
  );

  const toggleLeft = (uid: string) =>
    setSelectedLeft((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });

  const toggleRight = (uid: string) =>
    setSelectedRight((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });

  const allLeftChecked =
    filteredOutside.length > 0 &&
    filteredOutside.every((u) => selectedLeft.has(u.id));
  const someLeftChecked = filteredOutside.some((u) => selectedLeft.has(u.id));
  const allRightChecked =
    filteredMembers.length > 0 &&
    filteredMembers.every((m) => selectedRight.has(m.user_id));
  const someRightChecked = filteredMembers.some((m) =>
    selectedRight.has(m.user_id),
  );

  const leftCheckState = allLeftChecked
    ? true
    : someLeftChecked
      ? 'indeterminate'
      : false;
  const rightCheckState = allRightChecked
    ? true
    : someRightChecked
      ? 'indeterminate'
      : false;

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

        <CardHeader className="pb-6 border-b-0.5 dark:border-border-button shrink-0 space-y-4">
          <h1 className="text-xl font-semibold">{t('setting.teamMembers')}</h1>
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
        </CardHeader>

        <CardContent className="h-0 basis-0 grow pt-4 flex gap-3 min-h-0">
          {/* Left panel — users not in team */}
          <div className="flex-1 flex flex-col min-h-0 rounded-md border border-border-button">
            <div className="px-3 py-2 border-b border-border-button shrink-0 space-y-2">
              <div className="flex items-center gap-2">
                <Checkbox
                  checked={leftCheckState}
                  onCheckedChange={(c) => {
                    if (c === true)
                      setSelectedLeft(
                        new Set(filteredOutside.map((u) => u.id)),
                      );
                    else setSelectedLeft(new Set());
                  }}
                />
                <span className="text-sm font-medium">
                  {t('admin.usersNotInTeam')}
                </span>
                <Badge variant="outline" className="ml-auto text-xs">
                  {selectedLeft.size > 0
                    ? `${selectedLeft.size} / ${filteredOutside.length}`
                    : filteredOutside.length}
                </Badge>
              </div>
              <Input
                placeholder={t('admin.filterUsers')}
                value={leftFilter}
                onChange={(e) => setLeftFilter(e.target.value)}
                className="h-8 text-sm"
              />
            </div>
            <ScrollArea className="flex-1">
              <div className="p-1">
                {filteredOutside.length === 0 ? (
                  <p className="text-sm text-text-secondary text-center py-8">
                    —
                  </p>
                ) : (
                  filteredOutside.map((user) => (
                    <OutsideUserRow
                      key={user.id}
                      user={user}
                      checked={selectedLeft.has(user.id)}
                      onToggle={toggleLeft}
                    />
                  ))
                )}
              </div>
            </ScrollArea>
          </div>

          {/* Center controls */}
          <div className="flex flex-col items-center justify-center gap-2 shrink-0 w-28">
            <Button
              variant="outline"
              size="sm"
              className="w-full gap-1 text-xs"
              disabled={selectedLeft.size === 0 || addMutation.isPending}
              title={t('admin.addToTeam')}
              onClick={() => addMutation.mutate([...selectedLeft])}
            >
              {t('admin.addToTeam')}
              <LucideChevronRight className="size-3.5 shrink-0" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="w-full gap-1 text-xs"
              disabled={selectedRight.size === 0 || removeMutation.isPending}
              title={t('admin.removeFromTeam')}
              onClick={() => removeMutation.mutate([...selectedRight])}
            >
              <LucideChevronLeft className="size-3.5 shrink-0" />
              {t('admin.removeFromTeam')}
            </Button>
          </div>

          {/* Right panel — team members */}
          <div className="flex-1 flex flex-col min-h-0 rounded-md border border-border-button">
            <div className="px-3 py-2 border-b border-border-button shrink-0 space-y-2">
              <div className="flex items-center gap-2">
                <Checkbox
                  checked={rightCheckState}
                  onCheckedChange={(c) => {
                    if (c === true)
                      setSelectedRight(
                        new Set(filteredMembers.map((m) => m.user_id)),
                      );
                    else setSelectedRight(new Set());
                  }}
                />
                <span className="text-sm font-medium">
                  {t('setting.teamMembers')}
                </span>
                <Badge variant="outline" className="ml-auto text-xs">
                  {selectedRight.size > 0
                    ? `${selectedRight.size} / ${filteredMembers.length}`
                    : filteredMembers.length}
                </Badge>
              </div>
              <Input
                placeholder={t('admin.filterUsers')}
                value={rightFilter}
                onChange={(e) => setRightFilter(e.target.value)}
                className="h-8 text-sm"
              />
            </div>
            <ScrollArea className="flex-1">
              <div className="p-1">
                {filteredMembers.length === 0 ? (
                  <p className="text-sm text-text-secondary text-center py-8">
                    —
                  </p>
                ) : (
                  filteredMembers.map((member) => (
                    <MemberRow
                      key={member.user_id}
                      member={member}
                      checked={selectedRight.has(member.user_id)}
                      onToggle={toggleRight}
                      onValidate={(uid) => validateInviteMutation.mutate(uid)}
                    />
                  ))
                )}
              </div>
            </ScrollArea>
          </div>
        </CardContent>
      </Card>
    </section>
  );
}

export default AdminUserOwnTeam;
